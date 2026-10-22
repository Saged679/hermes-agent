"""Shared config→env bridge for media-delivery policy.

``validate_media_delivery_path`` reads ``HERMES_MEDIA_DELIVERY_STRICT`` (gateway.strict),
``HERMES_MEDIA_ALLOW_DIRS`` (gateway.media_delivery_allow_dirs) and
``HERMES_MEDIA_TRUST_RECENT_FILES`` (gateway.trust_recent_files).  Every delivery
entrypoint (gateway startup, ``hermes cron run``, ``hermes send``) calls
:func:`apply_media_policy_env` first so standalone paths filter under the gateway's
policy instead of silently dropping attachments in strict/allowlisted deployments.
An explicitly-set env var WINS over config.yaml, so shell overrides survive. Under a HERMES_HOME
override (a served profile's turn or cron fire) nothing is bridged: readers load that profile's config.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ALLOW_DIRS_ENV = "HERMES_MEDIA_ALLOW_DIRS"
_TRUST_RECENT_SECONDS_ENV = "HERMES_MEDIA_TRUST_RECENT_SECONDS"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off", ""})
# (config key, env var, default): ``strict`` is opt-in (only a known truthy value turns it on) and
# ``trust_recent_files`` is opt-out (only a known falsy value turns it off). The default is the
# knob's own, so a missing value and an unreadable one behave the same.
_FLAGS = (
    ("strict", "HERMES_MEDIA_DELIVERY_STRICT", False),
    ("trust_recent_files", "HERMES_MEDIA_TRUST_RECENT_FILES", True),
)


def _flag_value(value: Any, *, default: bool) -> bool:
    """One reading of a media-policy flag, shared by every path that reads one.

    A known truthy value is on, a known falsy one is off, anything else keeps the knob's
    default. The ENV readers already worked this way; the CONFIG path read the value with
    ``bool()``, so a quoted "false" meant TRUE there - the opposite of the same setting on
    the env path, and of what the operator wrote."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return default


def _routed_gateway_cfg() -> Optional[dict[str, Any]]:
    """``gateway`` section of the ROUTED profile's config when a HERMES_HOME override is active
    (multiplexed turn), else None. The env bridge is one process-wide copy of the launch profile's
    policy, so a secondary's deliveries must read their own config instead of ``os.environ``."""
    from hermes_constants import get_hermes_home_override
    if not get_hermes_home_override():
        return None
    try:
        from hermes_cli.config import load_config_readonly
        gateway_cfg = load_config_readonly().get("gateway")
    except Exception:
        return {}
    return gateway_cfg if isinstance(gateway_cfg, dict) else {}


def media_delivery_strict() -> bool:
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return _flag_value(cfg.get("strict"), default=False)
    return _flag_value(os.environ.get(_FLAGS[0][1]), default=False)


def media_delivery_allow_dirs() -> str:
    """Operator allowlist as the ``os.pathsep``-joined string the validator splits."""
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return _allow_dirs_str(cfg.get("media_delivery_allow_dirs"))
    return os.environ.get(_ALLOW_DIRS_ENV, "")


def media_delivery_trust_recent() -> bool:
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return _flag_value(cfg.get("trust_recent_files"), default=True)
    return _flag_value(os.environ.get(_FLAGS[1][1]), default=True)


def media_delivery_trust_recent_seconds() -> str:
    """Raw recency window (``""`` = validator default); the caller parses/floors it."""
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        raw = cfg.get("trust_recent_files_seconds")
        return "" if raw is None else str(raw)
    return os.environ.get(_TRUST_RECENT_SECONDS_ENV, "")



def _load_gateway_cfg(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config() or {}
        except Exception:
            return {}
    gateway_cfg = config.get("gateway", {})
    return gateway_cfg if isinstance(gateway_cfg, dict) else {}


def _set_env_default(env: str, value: str) -> None:
    """Set ``env`` only when unset/empty and ``value`` is non-empty (env wins)."""
    if value and not os.environ.get(env):
        os.environ[env] = value


def _allow_dirs_str(allow_dirs: Any) -> str:
    if isinstance(allow_dirs, (list, tuple)):
        return os.pathsep.join(str(p) for p in allow_dirs if p)
    return allow_dirs if isinstance(allow_dirs, str) else ""


def apply_media_policy_env(config: Optional[dict[str, Any]] = None) -> None:
    """Bridge gateway media-policy settings from config.yaml into the env.  Idempotent,
    env-wins, never raises — a bridge failure must not break delivery (validator defaults apply).

    No-op under a HERMES_HOME override, the same gate the readers use: there they take the
    profile's own config (``_routed_gateway_cfg``), and ``os.environ`` is shared — a routed cron
    fire would hand its allowlist and strictness to the launch profile and its children."""
    try:
        from hermes_constants import get_hermes_home_override
        if get_hermes_home_override():
            return
        gateway_cfg = _load_gateway_cfg(config)
        if not gateway_cfg:
            return
        for key, env, default in _FLAGS:
            flag = gateway_cfg.get(key)
            if flag is not None:
                _set_env_default(env, "1" if _flag_value(flag, default=default) else "0")
        allow_dirs = gateway_cfg.get("media_delivery_allow_dirs")
        if allow_dirs:
            _set_env_default(_ALLOW_DIRS_ENV, _allow_dirs_str(allow_dirs))
    except Exception:
        logger.debug("apply_media_policy_env failed", exc_info=True)
