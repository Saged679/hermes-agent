"""The media-delivery policy must read one flag one way, on every path.

``gateway.strict`` and ``gateway.trust_recent_files`` are read from the ROUTED profile's own
config (a context-local home override) and, for the launch profile, through the env bridge that
copies config.yaml into ``HERMES_MEDIA_DELIVERY_STRICT`` /
``HERMES_MEDIA_TRUST_RECENT_FILES``. The ENV readers were string-aware; the CONFIG path read the
value with ``bool()``, so a quoted "false" meant TRUE there - the opposite of the same setting on
the env path, and of what the operator wrote.

The env path stays the reference: an opt-in knob (``strict``) is on only for a known truthy value
and an opt-out knob (``trust_recent_files``) is off only for a known falsy one.
"""

from __future__ import annotations

import os

import pytest

from gateway.media_policy import (
    apply_media_policy_env,
    media_delivery_strict,
    media_delivery_trust_recent,
)

_FLAG_ENVS = ("HERMES_MEDIA_DELIVERY_STRICT", "HERMES_MEDIA_TRUST_RECENT_FILES")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A Hermes home with a config.yaml, and no routed-profile scope bound."""
    path = tmp_path / "hermes-home"
    path.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(path))
    for var in _FLAG_ENVS:
        monkeypatch.delenv(var, raising=False)
    return path


@pytest.fixture()
def routed_home(home, monkeypatch):
    """The same home, bound as the ROUTED profile's scope (the config path)."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(str(home))
    try:
        yield home
    finally:
        reset_hermes_home_override(token)


def _write_config(home, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")


def test_a_quoted_false_does_not_re_enable_trusting_recent_files(routed_home):
    """The opt-out the operator wrote must be the opt-out they get."""
    _write_config(routed_home, 'gateway:\n  trust_recent_files: "false"\n')

    assert media_delivery_trust_recent() is False


def test_a_quoted_false_does_not_turn_on_strict_delivery(routed_home):
    """Strict delivery drops files outside the allowlist: a quoted "false" must not enable it."""
    _write_config(routed_home, 'gateway:\n  strict: "false"\n')

    assert media_delivery_strict() is False


def test_a_real_yaml_false_still_turns_them_off(routed_home):
    """The control: the ordinary spelling keeps working."""
    _write_config(routed_home, "gateway:\n  trust_recent_files: false\n  strict: false\n")

    assert media_delivery_trust_recent() is False
    assert media_delivery_strict() is False


def test_a_missing_key_keeps_the_knob_its_default(routed_home):
    """An unset key keeps the knob's own default (trust recent: on, strict: off)."""
    _write_config(routed_home, "gateway:\n  media_delivery_allow_dirs: []\n")

    assert media_delivery_trust_recent() is True
    assert media_delivery_strict() is False


def test_the_bridge_copies_the_same_reading_into_the_env(home):
    """The launch profile reads the env the bridge wrote: it must carry the same answer."""
    _write_config(home, 'gateway:\n  trust_recent_files: "false"\n  strict: "false"\n')

    apply_media_policy_env()

    assert os.environ.get("HERMES_MEDIA_TRUST_RECENT_FILES") == "0"
    assert os.environ.get("HERMES_MEDIA_DELIVERY_STRICT") == "0"


def test_the_env_path_still_reads_the_flag_the_same_way(home, monkeypatch):
    """The env reader is the reference: its behaviour is unchanged by the fix."""
    monkeypatch.setenv("HERMES_MEDIA_TRUST_RECENT_FILES", "0")
    monkeypatch.setenv("HERMES_MEDIA_DELIVERY_STRICT", "0")

    assert media_delivery_trust_recent() is False
    assert media_delivery_strict() is False

    monkeypatch.setenv("HERMES_MEDIA_TRUST_RECENT_FILES", "1")
    monkeypatch.setenv("HERMES_MEDIA_DELIVERY_STRICT", "1")

    assert media_delivery_trust_recent() is True
    assert media_delivery_strict() is True


def test_the_env_path_agrees_with_the_config_path(routed_home, home, monkeypatch):
    """The invariant: the same setting cannot mean two things depending on who read it."""
    _write_config(routed_home, 'gateway:\n  trust_recent_files: "false"\n  strict: "false"\n')

    # The config path (the routed profile) and the env path (the launch profile, through the
    # bridge) must answer the same.
    routed = (media_delivery_trust_recent(), media_delivery_strict())
    apply_media_policy_env()
    env_path = (media_delivery_trust_recent(), media_delivery_strict())

    assert routed == env_path == (False, False)
