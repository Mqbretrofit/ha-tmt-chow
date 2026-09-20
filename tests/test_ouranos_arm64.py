"""Regression tests for the bundled ARM64 OURANOS runtime assets."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
NATIVE = ROOT / "custom_components" / "tmt_chow" / "native"
ARM64_MODULE = ROOT / "custom_components" / "tmt_chow" / "ouranos_arm64.py"
PROBE_MODULE = ROOT / "custom_components" / "tmt_chow" / "ouranos_ha_probe.py"
SESSION_MODULE = ROOT / "custom_components" / "tmt_chow" / "ouranos_native_session.py"

RUNTIME = NATIVE / "ouranos_bionic_runtime.arm64.tar.gz"
RUNTIME_SHA = NATIVE / "ouranos_bionic_runtime.arm64.tar.gz.sha256"
TUTK_MANIFEST = NATIVE / "ouranos_tutk_arm64_manifest.json"
PROBE_HELPER_SHA = NATIVE / "ouranos_bionic_helper.arm64.sha256"
SESSION_HELPER_SHA = NATIVE / "ouranos_bionic_session_helper.arm64.sha256"

EXPECTED_RUNTIME_MEMBERS = {
    "bin/ouranos_bionic_helper.arm64",
    "bin/ouranos_bionic_session_helper.arm64",
    "runtime/bin/linker64",
    "runtime/lib64/libc.so",
    "runtime/lib64/libdl.so",
    "runtime/lib64/libm.so",
    "runtime/lib64/libstdc++.so",
    "runtime-manifest.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_arm64_tutk_manifest_is_tmt_apk_pinned_and_complete() -> None:
    payload = json.loads(TUTK_MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["architecture"] == "aarch64"
    assert payload["abi"] == "arm64-v8a"
    assert payload["source_type"] == "tmt_apk"
    assert payload["source_package"] == "tw.timotion"
    assert payload["source_id"] == "tmt-chow-arm64-iotc-rdt-3.1.5.33"
    assert payload["source_path"] == "lib/arm64-v8a"
    assert payload["source_url"].startswith("https://d.apkpure.net/")
    assert set(payload["files"]) == {
        "libIOTCAPIs.so",
        "libRDTAPIs.so",
    }
    assert payload["files"]["libIOTCAPIs.so"] == {
        "apk_path": "lib/arm64-v8a/libIOTCAPIs.so",
        "sha256": "f5d7365b5c160f2d0195d9ffb109e490b076bb90a54146cf2a774758316e93f4",
        "size": 272024,
    }
    assert payload["files"]["libRDTAPIs.so"] == {
        "apk_path": "lib/arm64-v8a/libRDTAPIs.so",
        "sha256": "1e1edb740b27c14c8ff51c8efe303459e3a8e587a27afcd5eebb4841d4eda934",
        "size": 42400,
    }

def test_arm64_runtime_archive_is_integrity_pinned_and_minimal() -> None:
    expected = RUNTIME_SHA.read_text(encoding="ascii").strip()
    assert len(expected) == 64
    assert _sha256(RUNTIME) == expected

    with tarfile.open(RUNTIME, mode="r:gz") as archive:
        members = set()
        for member in archive.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if member.isfile():
                members.add(name)
    assert members == EXPECTED_RUNTIME_MEMBERS


def test_arm64_helper_hashes_match_the_bundled_runtime() -> None:
    with tarfile.open(RUNTIME, mode="r:gz") as archive:
        payloads = {}
        for member in archive.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if name in {
                "bin/ouranos_bionic_helper.arm64",
                "bin/ouranos_bionic_session_helper.arm64",
            }:
                source = archive.extractfile(member)
                assert source is not None
                payloads[name] = source.read()

    assert hashlib.sha256(
        payloads["bin/ouranos_bionic_helper.arm64"]
    ).hexdigest() == PROBE_HELPER_SHA.read_text(encoding="ascii").strip()
    assert hashlib.sha256(
        payloads["bin/ouranos_bionic_session_helper.arm64"]
    ).hexdigest() == SESSION_HELPER_SHA.read_text(encoding="ascii").strip()


def test_arm64_runtime_is_isolated_and_does_not_replace_x86_path() -> None:
    arm64_source = ARM64_MODULE.read_text(encoding="utf-8")
    probe_source = PROBE_MODULE.read_text(encoding="utf-8")
    session_source = SESSION_MODULE.read_text(encoding="utf-8")

    assert 'ARM64_MACHINES: Final = frozenset({"aarch64", "arm64"})' in arm64_source
    assert '"runtime/lib64/libstdc++.so"' in arm64_source
    assert "zipfile.ZipFile" in arm64_source
    assert "arm64_tmt_apk_library_integrity_failed" in arm64_source
    assert "TUTKGlobalAPIs" not in TUTK_MANIFEST.read_text(encoding="utf-8")
    assert "async_ensure_arm64_libraries" in probe_source
    assert "async_ensure_arm64_runtime" in probe_source
    assert "is_arm64_machine(machine)" in probe_source
    assert '"--library-path"' in probe_source
    assert "if is_arm64_machine():" in session_source
    assert '"--library-path"' in session_source
    assert "ouranos_glibc_session_helper.amd64" in session_source


def test_ps17062_uses_verified_status_and_guarded_parameter_arm64_route() -> None:
    init_source = (ROOT / "custom_components" / "tmt_chow" / "__init__.py").read_text(
        encoding="utf-8"
    )
    session_source = SESSION_MODULE.read_text(encoding="utf-8")
    helper_source = (
        ROOT / "tools" / "ouranos_glibc_session_helper.c"
    ).read_text(encoding="utf-8")

    assert "_is_verified_ps17062_read_status_candidate" in init_source
    assert 'hub.configured_controller_type in {"PS25142", "PS17062"}' in init_source
    assert 'status_command="READ_STATUS"' in init_source
    assert "expose_control_session=True" in init_source
    assert "_PS17062_PARAMETER_FRAGMENT_RE" in session_source
    assert "PARAM_WRITE_PS17062" in session_source
    assert "valid_ps17062_parameter_fragment" in helper_source
    assert "0123456789ABCDEFGHIJKLM" in helper_source
    assert "_is_verified_ouranos_poller_candidate" in init_source


def test_ps17062_movement_test_remains_explicit_and_guarded() -> None:
    init_source = (ROOT / "custom_components" / "tmt_chow" / "__init__.py").read_text(
        encoding="utf-8"
    )
    service_source = (
        ROOT / "custom_components" / "tmt_chow" / "services.yaml"
    ).read_text(encoding="utf-8")

    assert 'SERVICE_PS17062_MOVEMENT_TEST = "ps17062_movement_test"' in init_source
    assert 'call.data.get("confirm") is not True' in init_source
    assert "_is_verified_ps17062_read_status_candidate" in init_source
    assert "exactly one verified PS17062" in init_source
    assert "return await poller.async_movement_test(action)" in init_source
    assert "ps17062_movement_test:" in service_source
    assert "never" in service_source and "retried" in service_source
    assert "Normal cover movement controls remain disabled." in service_source
