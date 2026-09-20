"""ARM64/Bionic runtime support for the isolated OURANOS transport.

The TMT Android app uses an ARM64 Android (Bionic) ThroughTek runtime on
supported phones. Home Assistant OS on aarch64 uses a different userspace, so
the Android libraries are never loaded into Home Assistant Core. Instead they
are launched behind a small architecture-matched helper and a private,
integrity-checked Bionic runtime.

This module intentionally contains no gate-command policy. It only prepares the
native runtime and the pinned TUTK libraries; command allowlists remain in the
existing isolated helpers.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

ARM64_MACHINES: Final = frozenset({"aarch64", "arm64"})
_MAX_LIBRARY_BYTES: Final = 8 * 1024 * 1024
_MAX_APK_BYTES: Final = 220 * 1024 * 1024
_APK_DOWNLOAD_TIMEOUT: Final = 300
_APK_CHUNK_BYTES: Final = 4 * 1024 * 1024

_TUTK_MANIFEST_NAME: Final = "ouranos_tutk_arm64_manifest.json"
_RUNTIME_ARCHIVE_NAME: Final = "ouranos_bionic_runtime.arm64.tar.gz"
_RUNTIME_SHA_NAME: Final = _RUNTIME_ARCHIVE_NAME + ".sha256"
_PROBE_HELPER_SHA_NAME: Final = "ouranos_bionic_helper.arm64.sha256"
_SESSION_HELPER_SHA_NAME: Final = "ouranos_bionic_session_helper.arm64.sha256"

_RUNTIME_FILES: Final = frozenset(
    {
        "bin/ouranos_bionic_helper.arm64",
        "bin/ouranos_bionic_session_helper.arm64",
        "runtime/bin/linker64",
        "runtime/lib64/libc.so",
        "runtime/lib64/libdl.so",
        "runtime/lib64/libm.so",
        "runtime/lib64/libstdc++.so",
        "runtime-manifest.json",
    }
)


def is_arm64_machine(machine: str | None = None) -> bool:
    """Return whether the host is an ARM64 machine supported by this runtime."""
    value = (machine or platform.machine()).strip().lower()
    return value in ARM64_MACHINES


def _native_dir() -> Path:
    return Path(__file__).with_name("native")


def _read_expected_sha(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip().lower()
    except OSError as err:
        raise RuntimeError(f"arm64_integrity_file_missing:{path.name}") from err
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError(f"arm64_integrity_file_invalid:{path.name}")
    return value


def _load_tutk_manifest() -> dict[str, Any]:
    path = _native_dir() / _TUTK_MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as err:
        raise RuntimeError("arm64_tutk_manifest_unavailable") from err
    if not isinstance(payload, dict):
        raise RuntimeError("arm64_tutk_manifest_invalid")
    if (
        payload.get("schema_version") != 2
        or payload.get("architecture") != "aarch64"
        or payload.get("abi") != "arm64-v8a"
        or payload.get("source_type") != "tmt_apk"
    ):
        raise RuntimeError("arm64_tutk_manifest_incompatible")

    source_name = payload.get("source_name")
    source_package = payload.get("source_package")
    source_version = payload.get("source_version")
    source_id = payload.get("source_id")
    source_url = payload.get("source_url")
    source_path = payload.get("source_path")
    files = payload.get("files")
    if (
        not isinstance(source_name, str)
        or not source_name
        or source_package != "tw.timotion"
        or not isinstance(source_version, str)
        or not source_version
        or not isinstance(source_id, str)
        or not source_id
        or not isinstance(source_url, str)
        or not source_url.startswith("https://")
        or not isinstance(source_path, str)
        or source_path != "lib/arm64-v8a"
        or not isinstance(files, dict)
    ):
        raise RuntimeError("arm64_tutk_manifest_invalid")

    expected_names = {"libIOTCAPIs.so", "libRDTAPIs.so"}
    if set(files) != expected_names:
        raise RuntimeError("arm64_tutk_manifest_library_set_invalid")
    for name in expected_names:
        item = files.get(name)
        if not isinstance(item, dict):
            raise RuntimeError("arm64_tutk_manifest_invalid")
        digest = item.get("sha256")
        size = item.get("size")
        apk_path = item.get("apk_path")
        if (
            apk_path != f"{source_path}/{name}"
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size > _MAX_LIBRARY_BYTES
        ):
            raise RuntimeError("arm64_tutk_manifest_invalid")
    return payload

def arm64_source_metadata() -> dict[str, Any]:
    """Return non-secret pinned source metadata for diagnostics."""
    manifest = _load_tutk_manifest()
    return {
        "repository": manifest["source_name"],
        "commit": manifest["source_id"],
        "path": manifest["source_path"],
        "abi": manifest["abi"],
        "source_type": manifest["source_type"],
        "version": manifest["source_version"],
        "package": manifest["source_package"],
    }


async def _async_download_apk_to_file(
    hass: HomeAssistant,
    url: str,
    target: Path,
) -> None:
    """Stream the public TMT APK to disk with a hard size/time bound."""
    session = async_get_clientsession(hass)
    headers = {
        "User-Agent": "Mozilla/5.0 (Home Assistant; TMT Chow integration)",
        "Accept": "application/vnd.android.package-archive,application/octet-stream,*/*",
    }
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        await hass.async_add_executor_job(lambda: temp.parent.mkdir(parents=True, exist_ok=True))
        handle = await hass.async_add_executor_job(temp.open, "wb")
        total = 0
        try:
            async with asyncio.timeout(_APK_DOWNLOAD_TIMEOUT):
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    response.raise_for_status()
                    content_length = response.content_length
                    if content_length is not None and content_length > _MAX_APK_BYTES:
                        raise RuntimeError(
                            f"arm64_tmt_apk_size_invalid:{content_length}"
                        )
                    async for chunk in response.content.iter_chunked(_APK_CHUNK_BYTES):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > _MAX_APK_BYTES:
                            raise RuntimeError(
                                f"arm64_tmt_apk_size_invalid:{total}"
                            )
                        await hass.async_add_executor_job(handle.write, chunk)
        finally:
            await hass.async_add_executor_job(handle.close)
        if total <= 0:
            raise RuntimeError("arm64_tmt_apk_empty")
        await hass.async_add_executor_job(os.replace, temp, target)
    except RuntimeError:
        try:
            await hass.async_add_executor_job(temp.unlink, missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as err:
        try:
            await hass.async_add_executor_job(temp.unlink, missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(
            f"arm64_tmt_apk_download_failed:{type(err).__name__}"
        ) from err


def _extract_tutk_payloads_from_apk(
    apk_path: Path,
    manifest: dict[str, Any],
) -> dict[str, bytes]:
    """Extract only the two pinned TMT ARM64 TUTK libraries from the APK."""
    files: dict[str, dict[str, Any]] = manifest["files"]
    payloads: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(apk_path, mode="r") as archive:
            for name, metadata in files.items():
                apk_member = str(metadata["apk_path"])
                try:
                    info = archive.getinfo(apk_member)
                except KeyError as err:
                    raise RuntimeError(
                        f"arm64_tmt_apk_library_missing:{name}"
                    ) from err
                if info.is_dir() or info.file_size != int(metadata["size"]):
                    raise RuntimeError(
                        f"arm64_tmt_apk_library_size_invalid:{name}"
                    )
                if info.file_size > _MAX_LIBRARY_BYTES:
                    raise RuntimeError(
                        f"arm64_tmt_apk_library_size_invalid:{name}"
                    )
                payload = archive.read(info)
                actual_sha = hashlib.sha256(payload).hexdigest()
                expected_sha = str(metadata["sha256"]).lower()
                if actual_sha != expected_sha:
                    raise RuntimeError(
                        f"arm64_tmt_apk_library_integrity_failed:{name}:"
                        f"expected={expected_sha}:actual={actual_sha}"
                    )
                payloads[name] = payload
    except zipfile.BadZipFile as err:
        raise RuntimeError("arm64_tmt_apk_invalid_zip") from err

    if set(payloads) != set(files):
        raise RuntimeError("arm64_tmt_apk_library_set_invalid")
    return payloads

def _safe_install_tutk_libraries(
    payloads: dict[str, bytes],
    target: Path,
    manifest: dict[str, Any],
) -> None:
    files: dict[str, dict[str, Any]] = manifest["files"]
    if set(payloads) != set(files):
        raise RuntimeError("arm64_tutk_library_set_invalid")

    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for name, metadata in files.items():
            payload = payloads[name]
            expected_size = int(metadata["size"])
            expected_sha = str(metadata["sha256"]).lower()
            if len(payload) != expected_size:
                raise RuntimeError(f"arm64_tutk_library_size_invalid:{name}")
            actual_sha = hashlib.sha256(payload).hexdigest()
            if actual_sha != expected_sha:
                raise RuntimeError(
                    f"arm64_tutk_library_integrity_failed:{name}:"
                    f"expected={expected_sha}:actual={actual_sha}"
                )
            output = staging / name
            output.write_bytes(payload)
            os.chmod(output, 0o500)
        (staging / ".source-id").write_text(
            str(manifest["source_id"]), encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


async def async_ensure_arm64_libraries(
    hass: HomeAssistant,
) -> tuple[Path, Path, bool]:
    """Install the exact ARM64 IOTC/RDT pair shipped by TMT Chow."""
    manifest = _load_tutk_manifest()
    source_id = str(manifest["source_id"])
    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(
        lambda: cache_dir.mkdir(parents=True, exist_ok=True)
    )
    cache_key = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]
    target = cache_dir / f"tutk-arm64-{cache_key}"
    iotc = target / "libIOTCAPIs.so"
    rdt = target / "libRDTAPIs.so"
    marker = target / ".source-id"
    files: dict[str, dict[str, Any]] = manifest["files"]

    def existing_ok() -> bool:
        try:
            if marker.read_text(encoding="utf-8").strip() != source_id:
                return False
            for name, metadata in files.items():
                path = target / name
                if path.stat().st_size != int(metadata["size"]):
                    return False
                if hashlib.sha256(path.read_bytes()).hexdigest() != str(
                    metadata["sha256"]
                ).lower():
                    return False
            return True
        except OSError:
            return False

    if await hass.async_add_executor_job(existing_ok):
        return iotc, rdt, False

    apk_path = cache_dir / f"tmt-chow-arm64-{cache_key}.apk"
    try:
        await _async_download_apk_to_file(
            hass,
            str(manifest["source_url"]),
            apk_path,
        )
        payloads = await hass.async_add_executor_job(
            _extract_tutk_payloads_from_apk,
            apk_path,
            manifest,
        )
        await hass.async_add_executor_job(
            _safe_install_tutk_libraries,
            payloads,
            target,
            manifest,
        )
    finally:
        try:
            await hass.async_add_executor_job(apk_path.unlink, missing_ok=True)
        except OSError:
            pass

    return iotc, rdt, True

def _safe_extract_runtime(archive_data: bytes, target: Path, archive_sha: str) -> None:
    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as archive:
            for member in archive.getmembers():
                member_name = member.name
                while member_name.startswith("./"):
                    member_name = member_name[2:]
                if not member_name or member_name == ".":
                    continue
                relative = PurePosixPath(member_name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("arm64_runtime_archive_invalid")
                relative_text = relative.as_posix()
                if member.isdir():
                    if not any(
                        path.startswith(relative_text.rstrip("/") + "/")
                        for path in _RUNTIME_FILES
                    ):
                        raise RuntimeError("arm64_runtime_archive_invalid")
                    continue
                if (
                    relative_text not in _RUNTIME_FILES
                    or not member.isfile()
                    or member.issym()
                    or member.islnk()
                ):
                    raise RuntimeError("arm64_runtime_archive_invalid")
                if relative_text in seen:
                    raise RuntimeError("arm64_runtime_archive_duplicate")
                seen.add(relative_text)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError("arm64_runtime_archive_unreadable")
                output = staging.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(source.read())
                if relative_text.startswith("bin/") or relative_text == "runtime/bin/linker64":
                    os.chmod(output, 0o700)
                elif relative_text.startswith("runtime/lib64/"):
                    os.chmod(output, 0o500)
                else:
                    os.chmod(output, 0o400)

        if seen != set(_RUNTIME_FILES):
            raise RuntimeError("arm64_runtime_archive_incomplete")
        (staging / ".archive-sha256").write_text(archive_sha, encoding="ascii")
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _verify_runtime_files(target: Path, archive_sha: str) -> bool:
    try:
        if (
            (target / ".archive-sha256").read_text(encoding="ascii").strip()
            != archive_sha
        ):
            return False
        if not all((target / path).is_file() for path in _RUNTIME_FILES):
            return False
        probe_expected = _read_expected_sha(_native_dir() / _PROBE_HELPER_SHA_NAME)
        session_expected = _read_expected_sha(
            _native_dir() / _SESSION_HELPER_SHA_NAME
        )
        return (
            hashlib.sha256(
                (target / "bin/ouranos_bionic_helper.arm64").read_bytes()
            ).hexdigest()
            == probe_expected
            and hashlib.sha256(
                (target / "bin/ouranos_bionic_session_helper.arm64").read_bytes()
            ).hexdigest()
            == session_expected
        )
    except OSError:
        return False


async def async_ensure_arm64_runtime(
    hass: HomeAssistant,
) -> tuple[Path, Path, Path, Path, bool]:
    """Extract and verify the bundled Bionic loader/runtime and both helpers."""
    native = _native_dir()
    archive_path = native / _RUNTIME_ARCHIVE_NAME
    expected_sha = _read_expected_sha(native / _RUNTIME_SHA_NAME)
    try:
        archive_data = await hass.async_add_executor_job(archive_path.read_bytes)
    except OSError as err:
        raise RuntimeError("arm64_runtime_archive_missing") from err
    actual_sha = hashlib.sha256(archive_data).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError(
            "arm64_runtime_integrity_failed:"
            f"expected={expected_sha}:actual={actual_sha}"
        )

    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(
        lambda: cache_dir.mkdir(parents=True, exist_ok=True)
    )
    target = cache_dir / f"bionic-arm64-{expected_sha[:12]}"

    if not await hass.async_add_executor_job(
        _verify_runtime_files, target, expected_sha
    ):
        await hass.async_add_executor_job(
            _safe_extract_runtime, archive_data, target, expected_sha
        )
        if not await hass.async_add_executor_job(
            _verify_runtime_files, target, expected_sha
        ):
            raise RuntimeError("arm64_runtime_post_install_integrity_failed")
        installed = True
    else:
        installed = False

    return (
        target / "runtime/bin/linker64",
        target / "runtime/lib64",
        target / "bin/ouranos_bionic_helper.arm64",
        target / "bin/ouranos_bionic_session_helper.arm64",
        installed,
    )
