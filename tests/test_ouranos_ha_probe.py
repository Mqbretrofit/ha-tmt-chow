"""Regression tests for the Home Assistant-hosted OURANOS transport probe."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import types
import zipfile


ROOT = Path(__file__).parents[1]
PROBE_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_ha_probe.py"
HELPER_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_native_helper.py"
GLIBC_HELPER_PATH = (
    ROOT / "custom_components" / "tmt_chow" / "native" / "ouranos_glibc_helper.amd64"
)
GLIBC_HELPER_SHA_PATH = GLIBC_HELPER_PATH.with_suffix(".amd64.sha256")
GLIBC_HELPER_SOURCE = ROOT / "tools" / "ouranos_glibc_helper.c"
INIT_PATH = ROOT / "custom_components" / "tmt_chow" / "__init__.py"


def _load_probe():
    try:
        __import__("homeassistant.core")
    except ModuleNotFoundError:
        homeassistant = types.ModuleType("homeassistant")
        core = types.ModuleType("homeassistant.core")
        helpers = types.ModuleType("homeassistant.helpers")
        aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
        core.HomeAssistant = object
        aiohttp_client.async_get_clientsession = lambda hass: None
        sys.modules.setdefault("homeassistant", homeassistant)
        sys.modules.setdefault("homeassistant.core", core)
        sys.modules.setdefault("homeassistant.helpers", helpers)
        sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    spec = importlib.util.spec_from_file_location("tmt_chow_ouranos_ha_probe", PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_home_assistant_probe_uses_pinned_legacy_x64_sdk() -> None:
    probe = _load_probe()
    assert probe._SUPPORTED_MACHINES == frozenset({"x86_64", "amd64"})
    assert probe._TUTK_SDK_COMMIT == "1ef38620c25032ef7538b09da3f9c7b6830d6235"
    assert probe._TUTK_SDK_SHA256 == (
        "05463b5a35e83edc3c185b6173723ea191a4331530c97f097d74c48fed6943e7"
    )
    assert probe._TMT_APK_IOTC_VERSION == "0x03010521"
    assert probe._PROBE_IOTC_VERSION == "0x010d0700"


def test_twenty_character_uid_is_accepted_by_transport_probe() -> None:
    probe = _load_probe()
    result = probe._base_result("ABCDEFGHIJKLMNOPQRST")
    assert result["applicable"] is True
    assert result["safety"]["rdt_write_called"] is False
    assert result["safety"]["gate_command_sent"] is False
    assert result["safety"]["status_read_command_sent"] is False
    assert result["safety"]["parameter_read_command_sent"] is False
    assert result["safety"]["parameter_write_command_sent"] is False


def test_ha_action_requires_confirmed_ps19001_candidate() -> None:
    source = INIT_PATH.read_text(encoding="utf-8")
    assert 'hub.configured_controller_type == "PS19001"' in source
    assert "_is_known_ouranos_candidate(candidate)" in source
    assert "Selected gate is not a confirmed PS19001 OURANOS candidate" in source


def test_private_glibc_runtime_is_pinned() -> None:
    probe = _load_probe()
    assert probe._GLIBC_VERSION == "2.35-0"
    assert probe._GLIBC_URL.endswith("/2.35-0/glibc-bin-2.35-0-x86_64.tar.gz")
    assert probe._MAX_GLIBC_BUNDLE_BYTES == 64 * 1024 * 1024
    assert probe._MAX_GLIBC_BUNDLE_BYTES > 52_484_557
    assert probe._GLIBC_SHA512 == (
        "0aff0ec76f4d341957a792b8635c0770148eba9a5cb64f9bbd85228c14d9cb93"
        "c1a402063cab533a9f536f5f7be92c27bc5be8ed13c2b4f7aa416510c754d071"
    )


def test_ci_built_glibc_helper_hash_matches_probe() -> None:
    probe = _load_probe()
    assert GLIBC_HELPER_PATH.is_file()
    digest = hashlib.sha256(GLIBC_HELPER_PATH.read_bytes()).hexdigest()
    assert digest == probe._GLIBC_HELPER_SHA256
    assert GLIBC_HELPER_SHA_PATH.read_text(encoding="ascii").strip() == digest


def test_safe_glibc_bundle_extracts_only_private_runtime(tmp_path: Path) -> None:
    probe = _load_probe()
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        for name, data in (
            ("usr/glibc-compat/lib/ld-linux-x86-64.so.2", b"loader"),
            ("usr/glibc-compat/lib/libc.so.6", b"libc"),
            ("etc/should-not-be-extracted", b"nope"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))

    target = tmp_path / "glibc"
    probe._safe_extract_glibc_bundle(archive_buffer.getvalue(), target)

    assert (target / "usr/glibc-compat/lib/ld-linux-x86-64.so.2").read_bytes() == b"loader"
    assert (target / "usr/glibc-compat/lib/libc.so.6").read_bytes() == b"libc"
    assert not (target / "etc/should-not-be-extracted").exists()


def test_safe_tutk_archive_extracts_only_pinned_libraries(
    tmp_path: Path, monkeypatch
) -> None:
    probe = _load_probe()
    iotc = b"iotc-library"
    rdt = b"rdt-library"
    members = {
        "iotc": ("sdk/libIOTCAPIs.so", hashlib.sha256(iotc).hexdigest()),
        "rdt": ("sdk/libRDTAPIs.so", hashlib.sha256(rdt).hexdigest()),
    }
    monkeypatch.setattr(probe, "_TUTK_LIBRARY_MEMBERS", members)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, mode="w") as archive:
        archive.writestr("sdk/libIOTCAPIs.so", iotc)
        archive.writestr("sdk/libRDTAPIs.so", rdt)
        archive.writestr("sdk/should-not-be-extracted", b"nope")

    target = tmp_path / "tutk"
    probe._safe_extract_tutk_libraries(archive_buffer.getvalue(), target)

    assert (target / "libIOTCAPIs.so").read_bytes() == iotc
    assert (target / "libRDTAPIs.so").read_bytes() == rdt
    assert not (target / "should-not-be-extracted").exists()


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


def test_native_helpers_have_no_write_or_gate_command_path() -> None:
    python_source = HELPER_PATH.read_text(encoding="utf-8")
    c_source = GLIBC_HELPER_SOURCE.read_text(encoding="utf-8")

    assert ".RDT_Write(" not in python_source
    assert ".RDT_Write.argtypes" not in python_source
    assert ".RDT_Write.restype" not in python_source
    assert "RDT_Write" not in c_source

    for command in (
        "FULL OPEN",
        "FULL CLOSE",
        "PED OPEN",
        "READ FUNCTION",
        "c=RS",
    ):
        assert command not in python_source
        assert command not in c_source
