"""
Secure Python Execution Engine

Provides isolated Python code execution with:
- RestrictedPython for AST-level restrictions
- Resource limits (memory, CPU, output size)
- Controlled import system
- No filesystem or network access
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import os
import re
import resource
import shutil
import signal
import sys
import sysconfig
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from multiprocessing import Pipe, Process
from multiprocessing.connection import Connection
from typing import Any

from sandbox.core.config import get_config, SecurityConfig, ResourceLimitsConfig
from sandbox.core.exceptions import (
    PythonExecutionError,
    BannedOperationError,
    TimeoutError,
    MemoryLimitError,
    OutputSizeLimitError,
)
from sandbox.core.logging import get_logger, log_security_event
from sandbox.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    ExecutionStatus,
)

logger = get_logger(__name__)


@dataclass
class PythonExecutionResult(ExecutionResult):
    """Result of Python execution."""
    stdout: str = ""
    stderr: str = ""
    result_data: dict[str, Any] | None = None
    variables: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result_data": self.result_data,
        })
        return result


class CodeValidator:
    """
    Python code validator.

    Uses AST analysis to detect banned patterns before execution.
    """

    def __init__(self, security_config: SecurityConfig | None = None) -> None:
        config = get_config()
        self.security = security_config or config.security
        self.allowed_imports = set(self.security.allowed_python_imports)
        self.banned_patterns = self.security.banned_python_patterns

    def validate(self, code: str) -> list[str]:
        """
        Validate Python code.

        Returns list of validation errors (empty if valid).
        """
        errors: list[str] = []

        # Check for banned string patterns first (fast check)
        code_lower = code.lower()
        for pattern in self.banned_patterns:
            if pattern.lower() in code_lower:
                errors.append(f"Code contains banned pattern: {pattern}")
                log_security_event("blocked_python_pattern", pattern=pattern)

        # Parse and analyze AST
        try:
            tree = ast.parse(code)
            errors.extend(self._analyze_ast(tree))
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")

        return errors

    def _analyze_ast(self, tree: ast.AST) -> list[str]:
        """Analyze AST for security issues."""
        errors: list[str] = []

        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self._is_allowed_import(alias.name):
                        errors.append(f"Import not allowed: {alias.name}")
                        log_security_event("blocked_import", module=alias.name)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not self._is_allowed_import(module):
                    errors.append(f"Import not allowed: {module}")
                    log_security_event("blocked_import", module=module)

            # Check for dangerous function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in {"exec", "eval", "compile", "__import__", "open"}:
                        errors.append(f"Function not allowed: {func_name}")
                        log_security_event("blocked_function", function=func_name)

                elif isinstance(node.func, ast.Attribute):
                    # Check for dangerous attribute access
                    attr_chain = self._get_attribute_chain(node.func)
                    if self._is_dangerous_attribute(attr_chain):
                        errors.append(f"Attribute access not allowed: {attr_chain}")
                        log_security_event("blocked_attribute", attribute=attr_chain)

            # Check for dangerous attribute access
            elif isinstance(node, ast.Attribute):
                if node.attr.startswith("_"):
                    # Allow single underscore for pandas-style private methods
                    if node.attr.startswith("__") and not node.attr.endswith("__"):
                        errors.append(f"Access to dunder attribute not allowed: {node.attr}")

        return errors

    def _is_allowed_import(self, module: str) -> bool:
        """Check if module import is allowed."""
        # Check exact match
        if module in self.allowed_imports:
            return True

        # Check if it's a submodule of an allowed package
        for allowed in self.allowed_imports:
            if module.startswith(f"{allowed}."):
                return True

        return False

    def _get_attribute_chain(self, node: ast.Attribute) -> str:
        """Get full attribute chain as string."""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def _is_dangerous_attribute(self, chain: str) -> bool:
        """Check if attribute chain is dangerous."""
        dangerous = {
            "__class__", "__bases__", "__subclasses__", "__mro__",
            "__code__", "__globals__", "__dict__", "__builtins__",
            "func_globals", "gi_frame", "f_globals",
        }
        parts = chain.split(".")
        return any(part in dangerous for part in parts)


class SafeBuiltins:
    """
    Safe builtins for restricted execution.

    Provides a controlled set of built-in functions.
    """

    # Safe builtins that don't allow escape
    SAFE_BUILTINS = {
        # Type conversions
        "bool": bool,
        "int": int,
        "float": float,
        "str": str,
        "bytes": bytes,
        "bytearray": bytearray,
        "complex": complex,

        # Collections
        "list": list,
        "dict": dict,
        "set": set,
        "frozenset": frozenset,
        "tuple": tuple,

        # Iteration
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "reversed": reversed,
        "sorted": sorted,
        "iter": iter,
        "next": next,

        # Math and comparison
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "divmod": divmod,

        # Logic
        "all": all,
        "any": any,
        "len": len,

        # String
        "ord": ord,
        "chr": chr,
        "ascii": ascii,
        "repr": repr,
        "format": format,

        # Type checking
        "type": type,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "callable": callable,
        "hasattr": hasattr,

        # Other safe operations
        "print": print,
        "id": id,
        "hash": hash,
        "slice": slice,
        "object": object,
        "staticmethod": staticmethod,
        "classmethod": classmethod,
        "property": property,

        # Exceptions (for handling)
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "StopIteration": StopIteration,
        "RuntimeError": RuntimeError,
        "ZeroDivisionError": ZeroDivisionError,

        # None and bool constants
        "None": None,
        "True": True,
        "False": False,
    }

    @classmethod
    def get_safe_builtins(cls) -> dict[str, Any]:
        """Get dictionary of safe builtins."""
        return cls.SAFE_BUILTINS.copy()


class SafeImporter:
    """
    Controlled import system.

    Only allows importing from a whitelist of modules.
    """

    def __init__(self, allowed_modules: set[str]) -> None:
        self.allowed_modules = allowed_modules

    def safe_import(self, name: str, globals_: dict | None = None, locals_: dict | None = None,
                    fromlist: tuple = (), level: int = 0) -> Any:
        """Safe import function that only allows whitelisted modules.

        This is the ``__import__`` the executed code's ``import`` statements
        call. Only an absolute import of an allow-listed package (or a module
        inside one) goes through.
        """
        base_module = name.split(".")[0]
        if level != 0 or base_module not in self.allowed_modules:
            raise ImportError(f"Import of '{name}' is not allowed in sandbox")

        # What an import statement gets back depends on ``fromlist`` (the top
        # package for ``import a.b``, the module itself for ``from a.b import
        # c``), so the result is not remembered by name; sys.modules already
        # makes a repeated import cheap.
        return __import__(name, globals_, locals_, fromlist, 0)

    def preload_modules(self) -> dict[str, Any]:
        """Preload commonly used modules."""
        preloaded = {}

        # Data processing
        try:
            import pandas as pd
            preloaded["pd"] = pd
            preloaded["pandas"] = pd
        except ImportError:
            pass

        try:
            import numpy as np
            preloaded["np"] = np
            preloaded["numpy"] = np
        except ImportError:
            pass

        # Standard library
        import json
        import math
        import datetime
        import re
        import statistics
        import collections
        import itertools
        import functools

        preloaded.update({
            "json": json,
            "math": math,
            "datetime": datetime,
            "re": re,
            "statistics": statistics,
            "collections": collections,
            "itertools": itertools,
            "functools": functools,
        })

        # Visualization
        try:
            import plotly
            import plotly.express as px
            import plotly.graph_objects as go
            preloaded["plotly"] = plotly
            preloaded["px"] = px
            preloaded["go"] = go
        except ImportError:
            pass

        # ML/Stats
        try:
            import sklearn
            from sklearn.linear_model import LinearRegression
            preloaded["sklearn"] = sklearn
            preloaded["LinearRegression"] = LinearRegression
        except ImportError:
            pass

        try:
            import scipy
            from scipy import stats
            preloaded["scipy"] = scipy
            preloaded["stats"] = stats
        except ImportError:
            pass

        try:
            import statsmodels
            import statsmodels.api as sm
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            preloaded["statsmodels"] = statsmodels
            preloaded["sm"] = sm
            preloaded["ExponentialSmoothing"] = ExponentialSmoothing
        except ImportError:
            pass

        return preloaded


# =============================================================================
# Confinement of the process that runs caller code
# =============================================================================
#
# The code runs in a child of the sandbox process itself, so without these
# steps it starts with everything the sandbox has: its environment (database
# passwords, API keys), its open database connections, and every space's files
# on the same disk. Before the code runs, the child
#
#   1. drops the environment, except for locale, time zone and thread counts;
#   2. closes every file descriptor it inherited (the sandbox's sockets);
#   3. moves into an empty directory made for this run;
#   4. installs an audit hook that refuses, for the rest of the process's
#      life: files outside that directory and the Python installation,
#      network use, starting processes, and loading native code.
#
# An audit hook cannot be removed once added. It polices what Python itself
# does; it is not an operating-system boundary, and the validator and the
# restricted builtins still apply on top of it.

# Environment variables the child keeps.
_KEPT_ENV = ("LANG", "LC_ALL", "LC_CTYPE", "TZ", "PATH")
_KEPT_ENV_SUFFIXES = ("_NUM_THREADS",)

# What libraries read outside the Python installation: shared libraries, time
# zones, fonts, and the CPU / memory figures thread pools size themselves by.
_SYSTEM_READ_PATHS = (
    "/usr/lib", "/usr/lib64", "/lib", "/lib64",
    "/usr/share/zoneinfo", "/usr/share/fonts", "/etc/fonts",
    "/etc/localtime", "/etc/timezone", "/etc/mime.types",
    "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom",
    "/proc/cpuinfo", "/proc/meminfo", "/proc/self/cgroup",
    "/sys/fs/cgroup", "/sys/devices/system/cpu",
)

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

# Never allowed, whatever the arguments.
_REFUSED_EVENTS = {
    "os.exec": "starting programs",
    "os.fork": "starting processes (use n_jobs=1)",
    "os.forkpty": "starting processes",
    "os.spawn": "starting programs",
    "os.posix_spawn": "starting programs",
    "os.system": "starting programs",
    "os.startfile": "starting programs",
    "subprocess.Popen": "starting programs",
    "pty.spawn": "starting programs",
    "os.kill": "signalling processes",
    "os.killpg": "signalling processes",
    # Relative paths are judged from the run's directory, so the process stays
    # in it; and with no links in it, a path inside it cannot lead out of it.
    "os.chdir": "changing directory",
    "os.symlink": "creating links",
    "os.link": "creating links",
    "sqlite3.connect": "opening databases",
    "gc.get_objects": "inspecting other objects in memory",
    "gc.get_referrers": "inspecting other objects in memory",
    "gc.get_referents": "inspecting other objects in memory",
}

# Events whose first argument is a path that is only read.
_READ_PATH_EVENTS = frozenset({"os.listdir", "os.scandir", "os.getxattr", "os.listxattr"})

# Events that change the path(s) they name: {event: (argument positions of the
# paths, argument position of dir_fd or None)}.
_WRITE_PATH_EVENTS = {
    "os.mkdir": ((0,), 2),
    "os.rmdir": ((0,), 1),
    "os.remove": ((0,), 1),
    "os.rename": ((0, 1), None),
    "os.truncate": ((0,), None),
    "os.chmod": ((0,), 2),
    "os.chown": ((0,), 3),
    "os.utime": ((0,), 3),
    "os.chflags": ((0,), None),
    "os.setxattr": ((0,), None),
    "os.removexattr": ((0,), None),
}

# The only ctypes use left open: what threadpoolctl (scikit-learn, numpy) does
# to read and set BLAS / OpenMP thread counts. It opens libraries that are
# already loaded and looks up these symbols; nothing else can be looked up, so
# no other native function can be called.
_CTYPES_SYMBOLS = re.compile(
    r"dl_iterate_phdr"
    r"|(?:scipy_)?openblas_\w+"
    r"|omp_[gs]et_\w+"
    r"|MKL_\w+"
    r"|bli_\w+"
    r"|flexiblas_(?:current_backend|get_num_threads|set_num_threads|get_version|list|list_loaded)"
)
_CTYPES_HARMLESS_EVENTS = frozenset({
    "ctypes.create_string_buffer", "ctypes.create_unicode_buffer",
    "ctypes.get_errno", "ctypes.set_errno",
})


def _inside(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _library_roots() -> tuple[str, ...]:
    """Where the Python installation and its packages live (read-only to the code)."""
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    roots.update(sysconfig.get_paths().values())
    for entry in sys.path:
        if os.path.basename(entry.rstrip(os.sep)) in ("site-packages", "dist-packages"):
            roots.add(entry)
    roots.update(_SYSTEM_READ_PATHS)
    resolved = {os.path.realpath(root) for root in roots if root}
    resolved.discard(os.sep)
    return tuple(sorted(resolved))


def _install_audit_hook(workdir: str) -> None:
    """Refuse, from here on, what caller code has no business doing.

    ``workdir`` is the one place the code may write. See the note above.
    """
    work_roots = (os.path.realpath(workdir),)
    read_roots = _library_roots()
    devnull = os.path.realpath(os.devnull)

    def refuse(what: str) -> PermissionError:
        return PermissionError(f"The sandbox does not allow {what}")

    def resolve(path: Any, dir_fd: Any = None) -> str:
        """The real file a path names; raises for one that cannot be read."""
        if isinstance(path, int):  # an open descriptor
            return os.path.realpath(f"/proc/self/fd/{path}")
        text = os.fsdecode(os.fspath(path)) if path is not None else "."
        if isinstance(dir_fd, int) and dir_fd >= 0 and not os.path.isabs(text):
            text = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), text)
        return os.path.realpath(text)

    def check_read(path: Any) -> None:
        try:
            real = resolve(path)
        except (TypeError, ValueError, OSError):
            raise refuse("reading this path") from None
        if not (_inside(real, work_roots) or _inside(real, read_roots)):
            raise refuse(f"reading {real}")

    def check_write(path: Any, dir_fd: Any = None) -> None:
        try:
            real = resolve(path, dir_fd)
        except (TypeError, ValueError, OSError):
            raise refuse("changing this path") from None
        if not _inside(real, work_roots):
            raise refuse(f"changing {real}")

    def check_open(path: Any, flags: Any) -> None:
        if isinstance(path, int):  # re-wrapping a descriptor that is already open
            return
        try:
            real = resolve(path)
        except (TypeError, ValueError, OSError):
            raise refuse("opening this path") from None
        if _inside(real, work_roots) or real == devnull:
            return
        writing = not isinstance(flags, int) or bool(flags & _WRITE_FLAGS)
        # A directory descriptor would let later calls name files relative to
        # it, out of this hook's sight; outside the run's directory none is given.
        if writing or not _inside(real, read_roots) or os.path.isdir(real):
            raise refuse(f"{'writing' if writing else 'reading'} {real}")

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            check_open(args[0], args[2] if len(args) > 2 else None)
        elif event in _REFUSED_EVENTS:
            raise refuse(_REFUSED_EVENTS[event])
        elif event in _READ_PATH_EVENTS:
            check_read(args[0] if args else None)
        elif event in _WRITE_PATH_EVENTS:
            positions, dir_fd_position = _WRITE_PATH_EVENTS[event]
            dir_fd = (
                args[dir_fd_position]
                if dir_fd_position is not None and len(args) > dir_fd_position
                else None
            )
            for position in positions:
                check_write(args[position] if len(args) > position else None, dir_fd)
        elif event.startswith("socket."):
            if event not in ("socket.__new__", "socket.gethostname"):
                raise refuse("network access")
        elif event == "import":
            # Only a compiled extension module has a file name here.
            filename = args[1] if len(args) > 1 else None
            if filename and not _inside(os.path.realpath(filename), read_roots):
                raise refuse("loading native code")
        elif event.startswith("ctypes."):
            if event == "ctypes.dlopen":
                name = args[0] if args else None
                if isinstance(name, bytes):
                    name = os.fsdecode(name)
                # None is the running program; a bare name is a system library.
                if name is not None and os.sep in str(name):
                    if not _inside(os.path.realpath(str(name)), read_roots):
                        raise refuse("loading native code")
            elif event == "ctypes.dlsym":
                name = args[1] if len(args) > 1 else None
                if isinstance(name, bytes):
                    name = name.decode("ascii", "replace")
                if not isinstance(name, str) or not _CTYPES_SYMBOLS.fullmatch(name):
                    # AttributeError is what a missing symbol raises, so code
                    # that probes for optional symbols carries on.
                    raise AttributeError(f"The sandbox does not allow calling {name!r}")
            elif event not in _CTYPES_HARMLESS_EVENTS:
                raise refuse("native memory access")

    sys.addaudithook(hook)


def _confine_child(workdir: str, keep_fd: int) -> None:
    """Strip what the child inherited from the sandbox and lock it down."""
    kept = {
        name: value
        for name, value in os.environ.items()
        if name in _KEPT_ENV or name.endswith(_KEPT_ENV_SUFFIXES)
    }
    os.environ.clear()
    os.environ.update(kept)
    # Libraries that want a home, a cache or a scratch file get the run's directory.
    os.environ.update(HOME=workdir, TMPDIR=workdir, MPLCONFIGDIR=workdir, XDG_CACHE_HOME=workdir)
    tempfile.tempdir = workdir

    # Everything the sandbox had open: database connections, listening sockets,
    # other runs' pipes. Only the standard streams and this run's result pipe stay.
    for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        if fd > 2 and fd != keep_fd:
            try:
                os.close(fd)
            except OSError:
                pass  # already gone (the descriptor listdir itself was using)

    os.chdir(workdir)
    _install_audit_hook(workdir)


def _send_result(result_writer: Connection, payload: dict[str, Any]) -> None:
    """Hand the outcome to the sandbox as JSON.

    JSON, not pickle: what arrives is whatever the child wrote, and the child
    ran caller code. Values JSON has no form for are sent as text.
    """
    result_writer.send_bytes(
        json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    )


def _receive_result(result_reader: Connection, wait_seconds: float) -> dict[str, Any]:
    """The child's outcome, or what became of it when none arrives."""
    if not result_reader.poll(wait_seconds):
        return {"status": "timeout", "error": f"No result after {wait_seconds:.0f}s"}
    try:
        payload = result_reader.recv_bytes()
    except EOFError:
        return {
            "status": "error",
            "error": (
                "The Python process ended without a result: it was stopped by a "
                "resource limit (memory or CPU time) or ended itself"
            ),
            "error_type": "ProcessEnded",
        }
    result = json.loads(payload)
    if not isinstance(result, dict) or "status" not in result:
        raise ValueError("The Python process returned a malformed result")
    return result


def _execute_confined(
    code: str,
    input_data: dict[str, Any],
    allowed_imports: set[str],
    max_memory_mb: int,
    timeout_seconds: int,
    max_output_kb: int,
    result_writer: Connection,
    workdir: str,
) -> None:
    """
    Execute code in an isolated process.

    This function runs in a separate process with resource limits, confined
    as described above before the code is run.
    """
    # Set resource limits
    try:
        # Memory limit (soft and hard). RLIMIT_AS counts the whole address
        # space, and this process is a fork of the server: it starts out as
        # large as the server already is. The allowance is therefore what the
        # code may add on top of that, not an absolute size — an absolute cap
        # below the server's own size stops the child before it runs a line.
        memory_bytes = max_memory_mb * 1024 * 1024
        try:
            with open("/proc/self/statm") as statm:
                inherited_bytes = int(statm.read().split()[0]) * resource.getpagesize()
        except (OSError, ValueError, IndexError):
            inherited_bytes = 0
        address_space = inherited_bytes + memory_bytes
        resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))

        # CPU time limit
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds, timeout_seconds + 5))

        # Disable core dumps
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, resource.error) as e:
        # May fail on some systems, continue anyway
        pass

    # Capture stdout/stderr
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        # Build execution environment
        importer = SafeImporter(allowed_imports)
        preloaded = importer.preload_modules()

        # An `import` statement calls the `__import__` of the builtins the code
        # runs with, so that is where the allow-listing importer goes. It is the
        # only importer the code has: anything off the list is refused.
        safe_builtins = SafeBuiltins.get_safe_builtins()
        safe_builtins["__import__"] = importer.safe_import

        # One namespace for the run: the preloaded modules, the input data and
        # whatever the code defines. With separate globals and locals, functions
        # and lambdas the code defines cannot see its own top-level names. The
        # builtins go in last so no input variable can stand in for them.
        safe_locals = {
            **preloaded,
            "DATA_JSON": json.dumps(input_data.get("data", []), ensure_ascii=False, default=str),
            "INPUT_DATA": input_data.get("data", []),
            **input_data.get("variables", {}),
            "__builtins__": safe_builtins,
        }

        # Nothing of the sandbox's is within reach from here on. A failure to
        # confine is a failure of the run: the code never runs unconfined.
        _confine_child(workdir, result_writer.fileno())

        # Execute with output capture
        start_time = time.time()
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            exec(code, safe_locals)
        execution_time = time.time() - start_time

        # Check output size
        stdout_val = stdout_buffer.getvalue()
        if len(stdout_val) > max_output_kb * 1024:
            stdout_val = stdout_val[:max_output_kb * 1024] + "\n... [output truncated]"

        # Extract result variables
        result_vars = {}
        for key in ["result", "summary_text", "plotly_figure", "insight", "explanation", "output"]:
            if key in safe_locals:
                val = safe_locals[key]
                # Serialize if needed
                if isinstance(val, (dict, list)):
                    result_vars[key] = val
                else:
                    result_vars[key] = str(val) if val is not None else None

        _send_result(result_writer, {
            "status": "success",
            "stdout": stdout_val,
            "stderr": stderr_buffer.getvalue(),
            "variables": result_vars,
            "execution_time": execution_time,
        })

    except MemoryError:
        _send_result(result_writer, {
            "status": "memory_error",
            "error": "Memory limit exceeded",
        })

    except Exception as e:
        tb = traceback.format_exc()
        _send_result(result_writer, {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": tb,
            "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(),
        })


class PythonExecutor(BaseExecutor[PythonExecutionResult]):
    """
    Secure Python Execution Engine.

    Executes Python code in an isolated environment with:
    - AST-level code validation
    - Process isolation
    - Resource limits (memory, CPU)
    - Controlled imports
    """

    def __init__(
        self,
        config: ResourceLimitsConfig | None = None,
        security_config: SecurityConfig | None = None,
    ) -> None:
        super().__init__(config)
        sandbox_config = get_config()
        self.security = security_config or sandbox_config.security
        self.validator = CodeValidator(security_config)
        self.allowed_imports = set(self.security.allowed_python_imports)

    async def validate(self, context: ExecutionContext, **kwargs: Any) -> list[str]:
        """Validate Python execution request."""
        errors: list[str] = []

        code = kwargs.get("code")
        if not code:
            errors.append("Code is required")
            return errors

        if not isinstance(code, str):
            errors.append("Code must be a string")
            return errors

        # Validate code content
        errors.extend(self.validator.validate(code))

        return errors

    async def execute(
        self,
        context: ExecutionContext,
        *,
        code: str,
        input_data: dict[str, Any] | None = None,
    ) -> PythonExecutionResult:
        """
        Execute Python code in sandbox.

        Args:
            context: Execution context
            code: Python code to execute
            input_data: Input data available to the code (as DATA_JSON and INPUT_DATA)

        Returns:
            PythonExecutionResult with execution results
        """
        metrics = ExecutionMetrics()
        self._log_start(context, "python", code_preview=code[:100])

        try:
            # Get resource limits
            timeout = context.timeout_seconds or self.config.python_timeout_seconds
            max_memory = context.max_memory_mb or self.config.max_memory_mb
            max_output = context.max_output_size_kb or self.config.max_output_size_kb

            # Execute in isolated process
            result = await self._execute_isolated(
                code=code,
                input_data=input_data or {},
                timeout=timeout,
                max_memory_mb=max_memory,
                max_output_kb=max_output,
            )

            metrics.complete()

            if result["status"] == "success":
                execution_result = PythonExecutionResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.SUCCESS,
                    metrics=metrics,
                    stdout=result.get("stdout", ""),
                    stderr=result.get("stderr", ""),
                    variables=result.get("variables", {}),
                    result_data=result.get("variables", {}).get("result"),
                )
            elif result["status"] == "memory_error":
                raise MemoryLimitError(max_memory)
            elif result["status"] == "timeout":
                raise TimeoutError(
                    f"Python execution timed out after {timeout} seconds",
                    timeout_seconds=timeout,
                    execution_type="python",
                )
            else:
                execution_result = PythonExecutionResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    metrics=metrics,
                    error_message=result.get("error", "Unknown error"),
                    error_code=result.get("error_type", "ExecutionError"),
                    stdout=result.get("stdout", ""),
                    stderr=result.get("stderr", ""),
                )

            self._log_complete(
                context, execution_result, "python",
                has_result=bool(execution_result.result_data),
            )
            return execution_result

        except (TimeoutError, MemoryLimitError):
            raise
        except Exception as e:
            metrics.complete()
            self._log_error(context, e, "python")
            raise PythonExecutionError(
                f"Python execution failed: {e}",
                code=code,
                cause=e,
            )

    async def _execute_isolated(
        self,
        code: str,
        input_data: dict[str, Any],
        timeout: int,
        max_memory_mb: int,
        max_output_kb: int,
    ) -> dict[str, Any]:
        """Execute code in an isolated process."""
        # The one directory the code may write to; it exists for this run only.
        workdir = tempfile.mkdtemp(prefix="sandbox-python-")
        result_reader, result_writer = Pipe(duplex=False)

        # Create process
        process = Process(
            target=_execute_confined,
            args=(
                code,
                input_data,
                self.allowed_imports,
                max_memory_mb,
                timeout,
                max_output_kb,
                result_writer,
                workdir,
            ),
        )

        try:
            process.start()
            # The child holds its own copy; with ours closed, the pipe reports
            # end-of-file as soon as the child is gone.
            result_writer.close()

            # Wait for result with timeout
            # Use asyncio to avoid blocking
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _receive_result, result_reader, timeout + 5),
                timeout=timeout + 10,
            )
            return result
        except asyncio.TimeoutError:
            process.kill()
            process.join(timeout=1)
            return {"status": "timeout", "error": f"Execution timed out after {timeout}s"}
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            result_reader.close()
            shutil.rmtree(workdir, ignore_errors=True)
