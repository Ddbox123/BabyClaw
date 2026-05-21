"""Security guardrails for user-editable LLM configuration."""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse


MAX_LLM_PROBE_CONNECT_TIMEOUT_SECONDS = 10

_API_KEY_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,80}$")
_ALLOWED_API_KEY_ENV_PREFIXES = (
    "OPENAI_",
    "DEEPSEEK_",
    "ANTHROPIC_",
    "GOOGLE_",
    "DASHSCOPE_",
    "MINIMAX_",
    "MINIMAX",
    "SILICONFLOW_",
    "ZHIPU_",
    "GROQ_",
    "VIBELUTION_LLM_",
)
_FORBIDDEN_API_KEY_ENV_NAMES = {
    "ALLUSERSPROFILE",
    "ALL_PROXY",
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LOCALAPPDATA",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PSMODULEPATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}

_LOCAL_PROVIDER_KINDS = {"local", "ollama"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_REMOTE_PROVIDER_HOSTS = {
    "aliyun": {"dashscope.aliyuncs.com"},
    "anthropic": {"api.anthropic.com"},
    "deepseek": {"api.deepseek.com"},
    "google": {"generativelanguage.googleapis.com"},
    "groq": {"api.groq.com"},
    "minimax": {"api.minimax.io", "api.minimaxi.com"},
    "openai": {"api.openai.com"},
    "siliconflow": {"api.siliconflow.cn"},
    "zhipu": {"open.bigmodel.cn"},
}


def _read_field(node: Any, name: str, default: Any = "") -> Any:
    if isinstance(node, dict):
        return node.get(name, default)
    return getattr(node, name, default)


def _provider_label(provider: Any) -> str:
    provider_id = str(_read_field(provider, "provider_id", "") or "").strip()
    kind = str(_read_field(provider, "kind", "") or "").strip()
    return provider_id or kind or "provider"


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_blocked_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _is_local_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if normalized in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _assert_resolved_host_is_public(host: str, port: int, *, context: str) -> None:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"{context} host could not be resolved") from exc
    addresses: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addresses.add(str(sockaddr[0]))
    if not addresses:
        raise ValueError(f"{context} host could not be resolved")
    blocked = sorted(address for address in addresses if _is_blocked_ip(address))
    if blocked:
        raise ValueError(f"{context} resolves to a non-public network address")


def validate_llm_api_key_env(name: str, *, required: bool = False, context: str = "api_key_env") -> str:
    """Validate environment variable names used for LLM API keys."""

    env_name = str(name or "").strip()
    if not env_name:
        if required:
            raise ValueError(f"{context} is required")
        return ""
    if env_name in _FORBIDDEN_API_KEY_ENV_NAMES:
        raise ValueError(f"{context} cannot target system environment variable `{env_name}`")
    if not _API_KEY_ENV_PATTERN.match(env_name):
        raise ValueError(f"{context} must be an uppercase environment variable name")
    if not any(env_name.startswith(prefix) for prefix in _ALLOWED_API_KEY_ENV_PREFIXES):
        raise ValueError(f"{context} must use an approved LLM API key environment variable prefix")
    return env_name


def validate_llm_provider_target(provider: Any, *, context: str = "provider", resolve_dns: bool = False) -> None:
    """Validate a provider before it can drive an outbound LLM HTTP request."""

    label = _provider_label(provider)
    kind = str(_read_field(provider, "kind", "") or "").strip().lower()
    base_url = str(_read_field(provider, "base_url", "") or "").strip()
    provider_env = str(_read_field(provider, "api_key_env", "") or "").strip()
    if provider_env:
        validate_llm_api_key_env(provider_env, context=f"{context}.{label}.api_key_env")
    if not base_url:
        raise ValueError(f"{context}.{label}.base_url is required")

    parsed = urlparse(base_url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise ValueError(f"{context}.{label}.base_url must be an http(s) URL with a host")
    if parsed.username or parsed.password:
        raise ValueError(f"{context}.{label}.base_url must not include credentials")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{context}.{label}.base_url must not include params, query, or fragment")

    if kind in _LOCAL_PROVIDER_KINDS:
        if not _is_local_host(host):
            raise ValueError(f"{context}.{label}.base_url for local providers must target localhost")
        return

    if _is_local_host(host):
        raise ValueError(f"{context}.{label}.base_url targets localhost but provider kind is not local")
    if scheme != "https":
        raise ValueError(f"{context}.{label}.base_url for remote providers must use https")
    if _is_ip_address(host):
        if _is_blocked_ip(host):
            raise ValueError(f"{context}.{label}.base_url targets a non-public network address")
        raise ValueError(f"{context}.{label}.base_url for remote providers must use an approved provider host")

    allowed_hosts = _REMOTE_PROVIDER_HOSTS.get(kind)
    if not allowed_hosts or host not in allowed_hosts:
        raise ValueError(f"{context}.{label}.base_url host is not approved for provider kind `{kind or 'unknown'}`")
    if resolve_dns:
        port = parsed.port or (443 if scheme == "https" else 80)
        _assert_resolved_host_is_public(host, port, context=f"{context}.{label}.base_url")


def validate_llm_public_config(public_config: dict[str, Any], *, context: str = "publicConfig") -> None:
    """Validate all user-editable LLM provider targets and key env names."""

    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    if not isinstance(llm, dict):
        return
    providers = llm.get("providers", {})
    if isinstance(providers, dict):
        for provider_id, provider in providers.items():
            if isinstance(provider, dict):
                validate_llm_provider_target(provider, context=f"{context}.llm.providers.{provider_id}")

    model_library = llm.get("model_library", {})
    if isinstance(model_library, dict):
        for model_id, item in model_library.items():
            if not isinstance(item, dict):
                continue
            provider = item.get("provider")
            if isinstance(provider, dict):
                validate_llm_provider_target(provider, context=f"{context}.llm.model_library.{model_id}.provider")
            env_name = str(item.get("api_key_env", "") or "").strip()
            if env_name:
                validate_llm_api_key_env(env_name, context=f"{context}.llm.model_library.{model_id}.api_key_env")

    profiles = llm.get("profiles", {})
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            provider = profile.get("provider")
            if isinstance(provider, dict):
                validate_llm_provider_target(provider, context=f"{context}.llm.profiles.{profile_id}.provider")
            env_name = str(profile.get("api_key_env", "") or "").strip()
            if env_name:
                validate_llm_api_key_env(env_name, context=f"{context}.llm.profiles.{profile_id}.api_key_env")


def coerce_llm_probe_timeout(connect_timeout: Any, timeout: Any) -> int:
    """Clamp probe HTTP timeout to a short, bounded connection check."""

    try:
        connect_seconds = int(connect_timeout)
    except (TypeError, ValueError):
        connect_seconds = MAX_LLM_PROBE_CONNECT_TIMEOUT_SECONDS
    try:
        timeout_seconds = int(timeout)
    except (TypeError, ValueError):
        timeout_seconds = MAX_LLM_PROBE_CONNECT_TIMEOUT_SECONDS
    return max(1, min(connect_seconds, timeout_seconds, MAX_LLM_PROBE_CONNECT_TIMEOUT_SECONDS))


def redact_llm_probe_error(message: Any, *, api_key: str | None = None) -> str:
    """Return an error string that is safe to expose through config diagnostics."""

    text = str(message or "")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(r"(api[_-]?key=)[^&\s]+", r"\1[redacted]", text, flags=re.IGNORECASE)
    return text
