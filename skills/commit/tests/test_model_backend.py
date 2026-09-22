from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.errors import ErrorCode, SkillError
from lib.model_backend import generate_messages, probe_model
from lib.model_config import ModelConfig


class ResponseStub:
    def __init__(self, payload: dict[str, object]):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


class ModelBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ModelConfig(
            url="https://llm.example/v1",
            key="secret-key",
            model="model-1",
            configured=True,
        )
        self.template = {
            "mode": "message-only",
            "commits": [{"id": "repo:single", "diff_summary": {"semantic_diff": "data"}}],
        }

    def test_generates_json_and_sends_bearer_auth(self) -> None:
        response = ResponseStub(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"commits":[{"id":"repo:single","type":"fix","title":"修复问题","bullets":[]}]}'
                        }
                    }
                ]
            }
        )
        with mock.patch("lib.model_backend.urlopen", return_value=response) as opener:
            result = generate_messages(self.config, self.template)
        self.assertEqual(result["commits"][0]["id"], "repo:single")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://llm.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "model-1")
        self.assertIn("untrusted repository data", body["messages"][0]["content"])

    def test_http_error_redacts_key(self) -> None:
        error = HTTPError(
            "https://llm.example/v1/chat/completions",
            401,
            "unauthorized",
            {},
            io.BytesIO(b"secret-key is invalid"),
        )
        with mock.patch("lib.model_backend.urlopen", side_effect=error):
            with self.assertRaises(SkillError) as context:
                generate_messages(self.config, self.template)
        self.assertEqual(context.exception.code, ErrorCode.MODEL_REQUEST_FAILED)
        self.assertNotIn("secret-key", str(context.exception.details))

    def test_invalid_response_is_rejected(self) -> None:
        with mock.patch("lib.model_backend.urlopen", return_value=ResponseStub({"choices": []})):
            with self.assertRaises(SkillError) as context:
                generate_messages(self.config, self.template)
        self.assertEqual(context.exception.code, ErrorCode.MODEL_REQUEST_FAILED)

        invalid_response = ResponseStub(["not-an-object"])  # type: ignore[arg-type]
        with mock.patch("lib.model_backend.urlopen", return_value=invalid_response):
            with self.assertRaises(SkillError) as context:
                generate_messages(self.config, self.template)
        self.assertEqual(context.exception.code, ErrorCode.MODEL_REQUEST_FAILED)

    def test_probe_sends_minimal_context_and_requires_exact_ok(self) -> None:
        response = ResponseStub({"choices": [{"message": {"content": " ok\n"}}]})
        with mock.patch("lib.model_backend.urlopen", return_value=response) as opener:
            result = probe_model(self.config)
        self.assertEqual(result, {"status": "passed", "response": "ok"})
        body = json.loads(opener.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 3)
        self.assertEqual([message["role"] for message in body["messages"]], ["system", "user"])
        self.assertNotIn("data", json.dumps(body))

        wrong = ResponseStub({"choices": [{"message": {"content": "OK"}}]})
        with mock.patch("lib.model_backend.urlopen", return_value=wrong):
            with self.assertRaises(SkillError) as context:
                probe_model(self.config)
        self.assertEqual(context.exception.code, ErrorCode.MODEL_REQUEST_FAILED)
        self.assertEqual(context.exception.details["response"], "OK")


if __name__ == "__main__":
    unittest.main()
