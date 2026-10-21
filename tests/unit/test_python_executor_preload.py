"""The Python executor's libraries are imported once, by the server, not by every run.

Each run is a child process forked from the server, so a module the server has
imported is already loaded in the child. These tests check that the executor
loads them when it is created, that a run then works, and that what a run may
import is unchanged.
"""
import asyncio
import sys
import time
import unittest

from sandbox.execution.base import ExecutionContext
from sandbox.execution.python_executor import PythonExecutor


def run(executor, code, data=None):
    return asyncio.run(executor.execute(ExecutionContext(), code=code, input_data={"data": data or []}))


class PreloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = PythonExecutor()

    def test_the_libraries_are_loaded_when_the_executor_is_made(self):
        for name in ("pandas", "numpy", "plotly.graph_objects"):
            self.assertIn(name, sys.modules)

    def test_a_run_uses_them_without_importing_them_again(self):
        started = time.time()
        result = run(self.executor, "result = pd.DataFrame(INPUT_DATA)['v'].sum()", [{"v": 1}, {"v": 2}])
        self.assertEqual(result.variables.get("result"), "3")
        # A run that imported pandas itself took seconds; a fork with it loaded does not.
        self.assertLess(time.time() - started, 2.0)

    def test_what_a_run_may_import_is_unchanged(self):
        try:
            result = run(self.executor, "import os\nresult = os.getcwd()")
        except Exception:
            return  # refused before it ran
        self.assertIsNone(result.variables.get("result"))


if __name__ == "__main__":
    unittest.main()
