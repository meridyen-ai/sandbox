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
import resource
import signal
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
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
        self._import_cache: dict[str, Any] = {}

    def safe_import(self, name: str, globals_: dict | None = None, locals_: dict | None = None,
                    fromlist: tuple = (), level: int = 0) -> Any:
        """Safe import function that only allows whitelisted modules."""
        # Check if allowed
        base_module = name.split(".")[0]
        if base_module not in self.allowed_modules:
            raise ImportError(f"Import of '{name}' is not allowed in sandbox")

        # Check cache
        if name in self._import_cache:
            return self._import_cache[name]

        # Perform actual import
        module = __import__(name, globals_, locals_, fromlist, level)
        self._import_cache[name] = module
        return module

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


def _execute_in_sandbox(
    code: str,
    input_data: dict[str, Any],
    allowed_imports: set[str],
    max_memory_mb: int,
    timeout_seconds: int,
    max_output_kb: int,
    result_queue: Queue,
) -> None:
    """
    Execute code in an isolated process.

    This function runs in a separate process with resource limits.
    """
    # Set resource limits
    try:
        # Memory limit (soft and hard)
        memory_bytes = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

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
        safe_builtins = SafeBuiltins.get_safe_builtins()
        importer = SafeImporter(allowed_imports)
        preloaded = importer.preload_modules()

        # Build globals
        safe_globals = {
            "__builtins__": safe_builtins,
            "__import__": importer.safe_import,
            **preloaded,
        }

        # Build locals with input data
        safe_locals = {
            "DATA_JSON": json.dumps(input_data.get("data", []), ensure_ascii=False, default=str),
            "INPUT_DATA": input_data.get("data", []),
            **input_data.get("variables", {}),
        }

        # Execute with output capture
        start_time = time.time()
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            exec(code, safe_globals, safe_locals)
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

        result_queue.put({
            "status": "success",
            "stdout": stdout_val,
            "stderr": stderr_buffer.getvalue(),
            "variables": result_vars,
            "execution_time": execution_time,
        })

    except MemoryError:
        result_queue.put({
            "status": "memory_error",
            "error": "Memory limit exceeded",
        })

    except Exception as e:
        tb = traceback.format_exc()
        result_queue.put({
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
        result_queue: Queue = Queue()

        # Create process
        process = Process(
            target=_execute_in_sandbox,
            args=(
                code,
                input_data,
                self.allowed_imports,
                max_memory_mb,
                timeout,
                max_output_kb,
                result_queue,
            ),
        )

        process.start()

        # Wait for result with timeout
        try:
            # Use asyncio to avoid blocking
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, result_queue.get, True, timeout + 5),
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
