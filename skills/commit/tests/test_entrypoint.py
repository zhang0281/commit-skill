from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_skill.py"


class EntryPointTest(unittest.TestCase):
    def test_import_entrypoint_without_running_main(self) -> None:
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec = importlib.util.spec_from_file_location("commit_skill_entrypoint", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            self.assertTrue(hasattr(module, "main"))
        finally:
            try:
                sys.path.remove(str(SCRIPT.parent))
            except ValueError:
                pass
