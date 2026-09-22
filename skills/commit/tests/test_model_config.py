from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.model_config import (
    doctor_report,
    normalize_chat_endpoint,
    require_usable_model_config,
    resolve_model_config,
    safe_url,
)


class ModelConfigTest(unittest.TestCase):
    def test_no_custom_environment_preserves_host_mode(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = resolve_model_config()
            report = doctor_report()
        self.assertFalse(config.configured)
        self.assertFalse(config.usable)
        self.assertEqual(report["mode"], "existing")

    def test_lowercase_zsh_names_enable_custom_mode_and_are_masked(self) -> None:
        env = {
            "commit_url": "https://llm.example/v1?token=do-not-print#fragment",
            "commit_key": "sk-secret-key",
            "commit_model": "commit-model-1",
            "commit_timeout": "12.5",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = resolve_model_config()
            report = doctor_report()
        self.assertTrue(config.usable)
        self.assertEqual(config.endpoint, "https://llm.example/v1/chat/completions")
        self.assertEqual(report["model"], "commit-model-1")
        self.assertEqual(report["key_preview"], "sk...ey")
        self.assertNotIn("secret-key", str(report))
        self.assertNotIn("token=", str(report))
        self.assertEqual(report["sources"]["url"], "commit_url")

    def test_uppercase_aliases_and_partial_config(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"COMMIT_URL": "http://127.0.0.1:1234", "COMMIT_KEY": "key"},
            clear=True,
        ):
            config = resolve_model_config()
        self.assertTrue(config.configured)
        self.assertFalse(config.usable)
        self.assertTrue(any("model" in error for error in config.errors))
        with mock.patch.dict(
            os.environ,
            {"commit_url": "http://user:password@localhost:1", "commit_key": "key", "commit_model": "m"},
            clear=True,
        ):
            with self.assertRaises(SkillError) as context:
                require_usable_model_config()
        self.assertEqual(context.exception.code, ErrorCode.MODEL_CONFIG_INVALID)
        self.assertNotIn("password", str(context.exception.details))

        with mock.patch.dict(
            os.environ,
            {"commit_url": "https://llm.example/v1", "commit_key": "ke\ny", "commit_model": "m"},
            clear=True,
        ):
            with self.assertRaises(SkillError):
                require_usable_model_config()

        with mock.patch.dict(
            os.environ,
            {"commit_openai_base_url": "https://llm.example/v1", "commit_openai_api_key": "key", "commit_model": "m"},
            clear=True,
        ):
            self.assertTrue(resolve_model_config().usable)

    def test_endpoint_and_safe_url_normalization(self) -> None:
        self.assertEqual(normalize_chat_endpoint("https://x/v1/"), "https://x/v1/chat/completions")
        self.assertEqual(normalize_chat_endpoint("https://x/v1/chat/completions"), "https://x/v1/chat/completions")
        self.assertEqual(safe_url("https://user:pass@example.com/v1?secret=1#x"), "https://example.com/v1")
        with mock.patch.dict(
            os.environ,
            {"commit_url": "http://[invalid", "commit_key": "key", "commit_model": "m"},
            clear=True,
        ):
            report = doctor_report()
        self.assertFalse(report["active"])
        self.assertEqual(report["url"], "<invalid>")


if __name__ == "__main__":
    unittest.main()
