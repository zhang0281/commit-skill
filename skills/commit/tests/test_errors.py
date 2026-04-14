from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError, error_payload, ok_payload


class ErrorsTest(unittest.TestCase):
    def test_ok_payload(self) -> None:
        payload = ok_payload(answer=42)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["error_code"], "OK")
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["answer"], 42)

    def test_error_payload_with_and_without_details(self) -> None:
        err = SkillError(ErrorCode.GIT_ADD_FAILED, "boom", {"x": 1})
        self.assertEqual(err.name, "GIT_ADD_FAILED")
        payload = error_payload(err)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "GIT_ADD_FAILED")
        self.assertEqual(payload["details"], {"x": 1})

        err2 = SkillError(ErrorCode.INVALID_ARGUMENT, "bad")
        payload2 = error_payload(err2)
        self.assertNotIn("details", payload2)
