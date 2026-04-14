from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.models import CmdResult
from lib import signing


class SigningTest(unittest.TestCase):
    def test_current_env_without_tty_and_with_tty_error(self) -> None:
        with mock.patch.object(signing.sys.stdin, "isatty", return_value=False):
            env = signing.current_env()
            self.assertNotIn("GPG_TTY", env)

        with mock.patch.object(signing.sys.stdin, "isatty", return_value=True), mock.patch.object(signing.os, "ttyname", side_effect=OSError):
            env = signing.current_env()
            self.assertNotIn("GPG_TTY", env)

    def test_detect_signing_and_helpers(self) -> None:
        gpg_ok = CmdResult([], 0, "sec rsa4096/ABCDEF1234567890 2022-01-01 [SC]\n", "")
        gpgconf_ok = CmdResult([], 0, "", "")
        values = {
            ("commit.gpgsign", False): "true",
            ("commit.gpgsign", True): "",
            ("user.signingkey", False): "",
            ("user.signingkey", True): "",
        }

        def fake_get(repo: str, key: str, global_scope: bool = False) -> str:
            return values[(key, global_scope)]

        with mock.patch.object(signing, "current_env", return_value={"GPG_TTY": "/dev/pts/1"}), \
             mock.patch.object(signing, "gpgconf", return_value=gpgconf_ok), \
             mock.patch.object(signing, "gpg", return_value=gpg_ok), \
             mock.patch.object(signing, "git_get", side_effect=fake_get), \
             mock.patch.object(signing.sys.stdin, "isatty", return_value=True):
            payload = signing.detect_signing("/repo")
            self.assertTrue(payload["signing_available"])
            self.assertEqual(payload["suggested_sign_mode"], "signed")
            self.assertEqual(payload["secret_key_ids"], ["ABCDEF1234567890"])

            forced = signing.detect_signing("/repo", requested_sign_mode="unsigned")
            self.assertEqual(forced["suggested_sign_mode"], "unsigned")

        self.assertEqual(signing.resolve_sign_mode("auto", {"suggested_sign_mode": "signed"}), "signed")
        self.assertTrue(signing.is_gpg_failure("failed to sign the data"))
        self.assertFalse(signing.is_gpg_failure("plain error"))

    def test_detect_signing_without_match(self) -> None:
        gpg_out = CmdResult([], 0, "pub x\nsec malformed\n", "")
        with mock.patch.object(signing, "current_env", return_value={}), \
             mock.patch.object(signing, "gpgconf", return_value=CmdResult([], 1, "", "nope")), \
             mock.patch.object(signing, "gpg", return_value=gpg_out), \
             mock.patch.object(signing, "git_get", return_value=""), \
             mock.patch.object(signing.sys.stdin, "isatty", return_value=False):
            payload = signing.detect_signing("/repo")
            self.assertFalse(payload["signing_available"])
            self.assertEqual(payload["suggested_sign_mode"], "unsigned")
