from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit, urlunsplit

from .errors import ErrorCode, SkillError


DEFAULT_TIMEOUT_SECONDS = 90.0
MAX_TIMEOUT_SECONDS = 600.0

# Lowercase names are accepted because they are convenient in zshrc. Uppercase
# aliases are provided for conventional environment naming and portability.
ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "url": (
        "commit_url",
        "COMMIT_URL",
        "commit_base_url",
        "COMMIT_BASE_URL",
        "commit_openai_base_url",
        "COMMIT_OPENAI_BASE_URL",
        "commit_api_url",
        "COMMIT_API_URL",
    ),
    "key": (
        "commit_key",
        "COMMIT_KEY",
        "commit_api_key",
        "COMMIT_API_KEY",
        "commit_openai_api_key",
        "COMMIT_OPENAI_API_KEY",
    ),
    "model": (
        "commit_model",
        "COMMIT_MODEL",
    ),
    "timeout": (
        "commit_timeout",
        "COMMIT_TIMEOUT",
    ),
}
EnvSelection = dict[str, tuple[str, str] | None]
StringValues = dict[str, str]


def _read_env(name: str) -> tuple[str, str] | None:
    for env_name in ENV_ALIASES[name]:
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        value = raw.strip()
        if value:
            return value, env_name
    return None


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) < 6:
        return "*" * len(value)
    return f"{value[:2]}...{value[-2:]}"


def safe_url(value: str) -> str:
    """Remove userinfo, query, and fragment before a URL reaches diagnostics."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<invalid>"
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return "<invalid>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if port:
        hostname = f"{hostname}:{port}"
    netloc = hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def normalize_chat_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _validate_url(value: str) -> str | None:
    if any(char.isspace() for char in value):
        return "url 不能包含空白字符"
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        return f"url 解析失败: {exc}"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "url 必须是带主机名的 http 或 https URL"
    if parsed.username or parsed.password:
        return "url 不得内嵌用户名或密码"
    try:
        parsed.port
    except ValueError:
        return "url 端口无效"
    return None


def _validate_text(name: str, value: str) -> str | None:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return f"{name} 不能包含控制字符"
    return None


def _read_timeout() -> tuple[float, str | None, str | None]:
    selected = _read_env("timeout")
    if selected is None:
        return DEFAULT_TIMEOUT_SECONDS, None, None
    value, source = selected
    try:
        timeout = float(value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS, source, "timeout 必须是数字"
    if timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        return DEFAULT_TIMEOUT_SECONDS, source, f"timeout 必须在 0 到 {MAX_TIMEOUT_SECONDS:g} 秒之间"
    return timeout, source, None


def _config_errors(
    selected: EnvSelection,
    values: StringValues,
    configured: bool,
    timeout_error: str | None,
) -> list[str]:
    if not configured:
        return []
    errors: list[str] = []
    missing = [name for name in ("url", "key", "model") if not selected[name]]
    if missing:
        errors.append(f"自定义模型配置缺少: {', '.join(missing)}")
    if values["url"]:
        url_error = _validate_url(values["url"])
        if url_error:
            errors.append(url_error)
    for name in ("key", "model"):
        text_error = _validate_text(name, values[name])
        if text_error:
            errors.append(text_error)
    if timeout_error:
        errors.append(timeout_error)
    return errors


@dataclass(frozen=True)
class ModelConfig:
    url: str = ""
    key: str = ""
    model: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    sources: dict[str, str] | None = None
    configured: bool = False
    errors: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.configured and not self.errors

    @property
    def endpoint(self) -> str:
        return normalize_chat_endpoint(self.url) if self.url else ""

    def public_summary(self) -> dict[str, object]:
        mode = "custom-api" if self.configured else "existing"
        return {
            "mode": mode,
            "active": self.usable,
            "backend": "openai-compatible-chat-completions" if self.configured else "host-stdin",
            "url": safe_url(self.url) if self.url else None,
            "endpoint": safe_url(self.endpoint) if self.endpoint else None,
            "model": self.model or None,
            "key_set": bool(self.key),
            "key_preview": mask_secret(self.key) if self.key else None,
            "timeout_seconds": self.timeout_seconds,
            "sources": dict(self.sources or {}),
            "errors": list(self.errors),
        }


def resolve_model_config() -> ModelConfig:
    selected: dict[str, tuple[str, str] | None] = {name: _read_env(name) for name in ("url", "key", "model")}
    timeout, timeout_source, timeout_error = _read_timeout()
    configured = any(value is not None for value in selected.values())
    values = {name: value[0] if value else "" for name, value in selected.items()}
    sources = {name: value[1] for name, value in selected.items() if value}
    if timeout_source:
        sources["timeout"] = timeout_source

    errors = _config_errors(selected, values, configured, timeout_error)
    return ModelConfig(
        url=values["url"],
        key=values["key"],
        model=values["model"],
        timeout_seconds=timeout,
        sources=sources,
        configured=configured,
        errors=tuple(errors),
    )


def require_usable_model_config() -> ModelConfig | None:
    config = resolve_model_config()
    if config.configured and not config.usable:
        raise SkillError(
            ErrorCode.MODEL_CONFIG_INVALID,
            "自定义模型环境变量无效；请先运行 doctor 查看脱敏诊断",
            {"config": config.public_summary()},
        )
    return config if config.configured else None


def doctor_report() -> dict[str, object]:
    return resolve_model_config().public_summary()
