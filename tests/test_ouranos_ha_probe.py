"""Regression tests for the Home Assistant-hosted OURANOS transport probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
PROBE_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_ha_probe.py"
HELPER_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_native_helper.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("tmt_chow_ouranos_ha_probe", PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_git_blob_integrity_helper() -> None:
    probe = _load_probe()
    assert probe._git_blob_sha1(b"abc123") == "49fbc054731540fa68b565e398d3574fde7366e9"


def test_home_assistant_probe_supports_aarch64() -> None:
    probe = _load_probe()
    assert probe._LIBRARY_SOURCES["aarch64"] == (
        "lib.arm64",
        "a3ff9de4300ed869c2ba9a589a1bd1bfede979b6",
    )
    assert probe._LIBRARY_SOURCES["x86_64"][0] == "lib.amd64"
    assert probe._LIBRARY_SOURCES["armv7l"][0] == "lib.arm"


def test_twenty_character_uid_is_ouranos_probe_candidate() -> None:
    probe = _load_probe()
    result = probe._base_result("ABCDEFGHIJKLMNOPQRST")
    assert result["applicable"] is True
    assert result["safety"]["rdt_write_called"] is False
    assert result["safety"]["gate_command_sent"] is False
    assert result["safety"]["status_read_command_sent"] is False
    assert result["safety"]["parameter_read_command_sent"] is False
    assert result["safety"]["parameter_write_command_sent"] is False


def test_helper_stdout_parser_uses_last_json_object() -> None:
    probe = _load_probe()
    stdout = b"native log line\n{\"old\": true}\nmore native noise\n{\"rdt_connected\": true}\n"
    assert probe._parse_helper_stdout(stdout) == {"rdt_connected": True}


def test_helper_error_redacts_uid() -> None:
    probe = _load_probe()
    uid = "ABCDEFGHIJKLMNOPQRST"
    error = probe._safe_helper_error(f"failed for UID {uid}".encode(), uid)
    assert error == "failed for UID <redacted-uid>"
    assert uid not in error


def test_native_helper_has_no_write_or_gate_command_path() -> None:
    source = HELPER_PATH.read_text(encoding="utf-8")

    # RDT_Write may appear only in explanatory text/comments. It must never be
    # accessed as a ctypes symbol or called by the helper.
    assert ".RDT_Write(" not in source
    assert ".RDT_Write.argtypes" not in source
    assert ".RDT_Write.restype" not in source

    # Movement/status/parameter payloads are intentionally absent from this
    # first HA-native transport probe.
    for command in (
        "FULL OPEN",
        "FULL CLOSE",
        "PED OPEN",
        "READ FUNCTION",
        "c=RS",
    ):
        assert command not in source
