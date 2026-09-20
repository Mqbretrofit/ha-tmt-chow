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


def test_arm64_tutk_manifest_is_commit_pinned_and_complete() -> None:
    payload = json.loads(TUTK_MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["architecture"] == "aarch64"
    assert payload["abi"] == "arm64-v8a"
    assert payload["source_repository"] == "yanjuntext/NewJKDevice"
    assert payload["source_commit"] == "0423b6c0cfbf9156eb9990250b955f1f6aafcf20"
    assert payload["source_path"] == "tutk/libs/arm64-v8a"
    assert set(payload["files"]) == {
        "libIOTCAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    }
    for metadata in payload["files"].values():
        assert len(metadata["sha256"]) == 64
        int(metadata["sha256"], 16)
        assert 0 < metadata["size"] < 8 * 1024 * 1024


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
    assert "async_ensure_arm64_libraries" in probe_source
    assert "async_ensure_arm64_runtime" in probe_source
    assert "is_arm64_machine(machine)" in probe_source
    assert '"--library-path"' in probe_source
    assert "if is_arm64_machine():" in session_source
    assert '"--library-path"' in session_source
    assert "ouranos_glibc_session_helper.amd64" in session_source


def test_ps17062_remains_read_only_until_real_arm64_route_is_confirmed() -> None:
    init_source = (ROOT / "custom_components" / "tmt_chow" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "PS17062" not in init_source
    assert "_is_verified_ouranos_poller_candidate" in init_source
