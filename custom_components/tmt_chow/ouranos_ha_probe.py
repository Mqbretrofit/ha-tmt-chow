"""Home Assistant-hosted read-only OURANOS/TUTK transport probe.

The native TUTK library is never loaded into the Home Assistant Core process.
On x86_64 HAOS, where Core uses musl, the probe launches a tiny bundled glibc
helper through a private integrity-checked glibc loader/runtime. This avoids
relying on the host's missing ``ld-linux-x86-64.so.2`` and keeps native crashes
isolated from Home Assistant.

The probe is transport-only. It never calls RDT_Write and never sends a gate,
status-read, parameter-read, or parameter-write command.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_TUTK_SDK_COMMIT: Final = "1ef38620c25032ef7538b09da3f9c7b6830d6235"
_TUTK_SDK_ARCHIVE: Final = "TUTK_IOTC_Platform_14W42P1.zip"
_TUTK_SDK_URL: Final = (
    "https://raw.githubusercontent.com/nblavoie/wyzecam-api/"
    f"{_TUTK_SDK_COMMIT}/wyzecam-sdk/{_TUTK_SDK_ARCHIVE}"
)
_TUTK_SDK_SHA256: Final = (
    "05463b5a35e83edc3c185b6173723ea191a4331530c97f097d74c48fed6943e7"
)
_TUTK_LIBRARY_MEMBERS: Final[dict[str, tuple[str, str]]] = {
    "iotc": (
        "Lib/Linux/x64/libIOTCAPIs.so",
        "955557829e7aebd6d258320fb024b453f07493d3747bb0afb3294d9bbd45464d",
    ),
    "rdt": (
        "Lib/Linux/x64/libRDTAPIs.so",
        "5a5a59fc2490bafa88012a8df0d7f35ec51fcee214880f5439fc3c5951c17dca",
    ),
}
_SUPPORTED_MACHINES: Final = frozenset({"x86_64", "amd64"})
_TMT_APK_IOTC_VERSION: Final = "0x03010521"
_PROBE_IOTC_VERSION: Final = "0x010d0700"
_MAX_SDK_ARCHIVE_BYTES: Final = 80 * 1024 * 1024
_DOWNLOAD_TIMEOUT: Final = 45
_HELPER_TIMEOUT: Final = 40

_GLIBC_VERSION: Final = "2.35-0"
_GLIBC_URL: Final = (
    "https://github.com/sgerrand/docker-glibc-builder/releases/download/"
    f"{_GLIBC_VERSION}/glibc-bin-{_GLIBC_VERSION}-x86_64.tar.gz"
)
_GLIBC_SHA512: Final = (
    "0aff0ec76f4d341957a792b8635c0770148eba9a5cb64f9bbd85228c14d9cb93"
    "c1a402063cab533a9f536f5f7be92c27bc5be8ed13c2b4f7aa416510c754d071"
)
_MAX_GLIBC_BUNDLE_BYTES: Final = 32 * 1024 * 1024
_GLIBC_HELPER_SHA256: Final = (
    "0bd0e422a64080a8c9d66aaf820d8c5dda5ff9fb578a14b34b64f913d3677cd9"
)


def _base_result(uuid: str) -> dict[str, Any]:
    machine = platform.machine().lower()
    return {
        "result": "not_run",
        "applicable": len(uuid) == 20,
        "home_assistant_machine": machine,
        "home_assistant_platform": sys.platform,
        "library_source_commit": _TUTK_SDK_COMMIT,
        "library_source_archive": _TUTK_SDK_ARCHIVE,
        "library_architecture_supported": machine in _SUPPORTED_MACHINES,
        "library_downloaded": False,
        "library_integrity_verified": False,
        "iotc_library_integrity_verified": False,
        "rdt_library_integrity_verified": False,
        "tmt_apk_iotc_version": _TMT_APK_IOTC_VERSION,
        "probe_iotc_version_expected": _PROBE_IOTC_VERSION,
        "helper_runtime": "private_glibc" if machine in _SUPPORTED_MACHINES else None,
        "glibc_version": _GLIBC_VERSION if machine in _SUPPORTED_MACHINES else None,
        "glibc_runtime_downloaded": False,
        "glibc_runtime_integrity_verified": False,
        "glibc_helper_integrity_verified": False,
        "helper_started": False,
        "helper_exit_code": None,
        "helper_error": None,
        "native": None,
        "safety": {
            "mqtt_connected": False,
            "aws_certificate_requested": False,
            "aws_policy_requested": False,
            "rdt_write_called": False,
            "gate_command_sent": False,
            "status_read_command_sent": False,
            "parameter_read_command_sent": False,
            "parameter_write_command_sent": False,
        },
    }


async def _async_download(hass: HomeAssistant, url: str, max_bytes: int) -> bytes:
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(_DOWNLOAD_TIMEOUT):
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.read()
    except Exception as err:
        raise RuntimeError(f"download_failed:{type(err).__name__}") from err
    if not data or len(data) > max_bytes:
        raise RuntimeError(f"download_size_invalid:{len(data)}")
    return data


def _safe_extract_tutk_libraries(data: bytes, target: Path) -> None:
    """Extract only the two pinned x86-64 libraries from the SDK archive."""
    staging = target.with_name(target.name + ".tmp")
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for output_name, (member_name, expected_sha) in _TUTK_LIBRARY_MEMBERS.items():
            info = archive.getinfo(member_name)
            if info.file_size <= 0 or info.file_size > 2 * 1024 * 1024:
                raise RuntimeError(f"tutk_library_size_invalid:{output_name}")
            payload = archive.read(info)
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected_sha:
                raise RuntimeError(
                    f"tutk_library_integrity_failed:{output_name}:"
                    f"expected={expected_sha}:actual={actual}"
                )
            output = staging / f"lib{output_name.upper()}APIs.so"
            output.write_bytes(payload)
            os.chmod(output, 0o700)
    (staging / ".archive-sha256").write_text(_TUTK_SDK_SHA256, encoding="ascii")
    if target.exists():
        import shutil
        shutil.rmtree(target)
    os.replace(staging, target)


async def _async_ensure_libraries(hass: HomeAssistant) -> tuple[Path, Path, bool]:
    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(lambda: cache_dir.mkdir(parents=True, exist_ok=True))
    target = cache_dir / "tutk-14W42P1-x64"
    iotc = target / "libIOTCAPIs.so"
    rdt = target / "libRDTAPIs.so"
    marker = target / ".archive-sha256"

    def existing_ok() -> bool:
        try:
            return (
                marker.read_text(encoding="ascii").strip() == _TUTK_SDK_SHA256
                and hashlib.sha256(iotc.read_bytes()).hexdigest()
                == _TUTK_LIBRARY_MEMBERS["iotc"][1]
                and hashlib.sha256(rdt.read_bytes()).hexdigest()
                == _TUTK_LIBRARY_MEMBERS["rdt"][1]
            )
        except OSError:
            return False

    if await hass.async_add_executor_job(existing_ok):
        return iotc, rdt, False

    data = await _async_download(hass, _TUTK_SDK_URL, _MAX_SDK_ARCHIVE_BYTES)
    actual = hashlib.sha256(data).hexdigest()
    if actual != _TUTK_SDK_SHA256:
        raise RuntimeError(
            f"sdk_archive_integrity_failed:expected={_TUTK_SDK_SHA256}:actual={actual}"
        )
    await hass.async_add_executor_job(_safe_extract_tutk_libraries, data, target)
    return iotc, rdt, True


def _safe_extract_glibc_bundle(data: bytes, target: Path) -> None:
    staging = target.with_name(target.name + ".tmp")
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    allowed_prefixes = (
        PurePosixPath("usr/glibc-compat/lib"),
        PurePosixPath("usr/glibc-compat/lib64"),
    )
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            member_path = PurePosixPath(member.name.lstrip("./"))
            if not any(
                member_path == prefix or prefix in member_path.parents
                for prefix in allowed_prefixes
            ):
                continue
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError("glibc_archive_unsafe_path")
            output = staging.joinpath(*member_path.parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    raise RuntimeError("glibc_archive_unsafe_symlink")
                output.symlink_to(member.linkname)
                continue
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("glibc_archive_member_unreadable")
            output.write_bytes(source.read())
            os.chmod(output, member.mode & 0o777)

    loader = staging / "usr/glibc-compat/lib/ld-linux-x86-64.so.2"
    libc = staging / "usr/glibc-compat/lib/libc.so.6"
    if not loader.exists() or not libc.exists():
        raise RuntimeError("glibc_runtime_incomplete")
    (staging / ".bundle-sha512").write_text(_GLIBC_SHA512, encoding="ascii")
    if target.exists():
        import shutil
        shutil.rmtree(target)
    os.replace(staging, target)


async def _async_ensure_glibc_runtime(hass: HomeAssistant) -> tuple[Path, Path, bool]:
    cache = Path(hass.config.path(".storage", "tmt_chow_ouranos", "glibc-2.35"))
    loader = cache / "usr/glibc-compat/lib/ld-linux-x86-64.so.2"
    libdir = cache / "usr/glibc-compat/lib"
    marker = cache / ".bundle-sha512"

    def existing_ok() -> bool:
        try:
            return (
                loader.exists()
                and (libdir / "libc.so.6").exists()
                and marker.read_text(encoding="ascii").strip() == _GLIBC_SHA512
            )
        except OSError:
            return False

    if await hass.async_add_executor_job(existing_ok):
        return loader, libdir, False

    data = await _async_download(hass, _GLIBC_URL, _MAX_GLIBC_BUNDLE_BYTES)
    actual = hashlib.sha512(data).hexdigest()
    if actual != _GLIBC_SHA512:
        raise RuntimeError(
            f"glibc_integrity_failed:expected={_GLIBC_SHA512}:actual={actual}"
        )
    await hass.async_add_executor_job(_safe_extract_glibc_bundle, data, cache)
    return loader, libdir, True


def _verify_bundled_glibc_helper() -> Path:
    helper = Path(__file__).with_name("native") / "ouranos_glibc_helper.amd64"
    try:
        data = helper.read_bytes()
    except OSError as err:
        raise RuntimeError("glibc_helper_missing") from err
    actual = hashlib.sha256(data).hexdigest()
    if actual != _GLIBC_HELPER_SHA256:
        raise RuntimeError(
            f"glibc_helper_integrity_failed:expected={_GLIBC_HELPER_SHA256}:actual={actual}"
        )
    return helper


def _parse_helper_stdout(stdout: bytes) -> dict[str, Any] | None:
    text = stdout.decode("utf-8", "replace")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _safe_helper_error(stderr: bytes, uuid: str) -> str | None:
    text = stderr.decode("utf-8", "replace").replace(uuid, "<redacted-uid>").strip()
    return text[-1000:] if text else None


async def _async_run_process(
    argv: list[str], uuid: str, *, env: dict[str, str] | None = None
) -> tuple[asyncio.subprocess.Process, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate((uuid + "\n").encode("ascii")),
            timeout=_HELPER_TIMEOUT,
        )
    except TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process, stdout, stderr


async def async_probe_ouranos_on_ha(hass: HomeAssistant, uuid: str) -> dict[str, Any]:
    result = _base_result(uuid)
    if len(uuid) != 20:
        result["result"] = "not_applicable"
        return result

    machine = result["home_assistant_machine"]
    if machine not in _SUPPORTED_MACHINES:
        result["result"] = "unsupported_architecture"
        return result

    try:
        iotc_path, rdt_path, downloaded = await _async_ensure_libraries(hass)
    except RuntimeError as err:
        result["result"] = "library_unavailable"
        result["helper_error"] = str(err)
        return result

    result["library_downloaded"] = downloaded
    result["library_integrity_verified"] = True
    result["iotc_library_integrity_verified"] = True
    result["rdt_library_integrity_verified"] = True

    process: asyncio.subprocess.Process | None = None
    try:
        loader, libdir, glibc_downloaded = await _async_ensure_glibc_runtime(hass)
        result["glibc_runtime_downloaded"] = glibc_downloaded
        result["glibc_runtime_integrity_verified"] = True
        helper = await hass.async_add_executor_job(_verify_bundled_glibc_helper)
        result["glibc_helper_integrity_verified"] = True
        argv = [
            str(loader),
            "--library-path",
            str(libdir),
            str(helper),
            str(iotc_path),
            str(rdt_path),
        ]
        env = {**os.environ, "LD_LIBRARY_PATH": str(libdir)}

        process, stdout, stderr = await _async_run_process(argv, uuid, env=env)
        result["helper_started"] = True
    except TimeoutError:
        result["result"] = "helper_timeout"
        result["helper_error"] = "native helper exceeded safety timeout"
        return result
    except RuntimeError as err:
        result["result"] = "helper_runtime_unavailable"
        result["helper_error"] = str(err)
        return result
    except Exception as err:
        result["result"] = "helper_start_failed"
        result["helper_error"] = type(err).__name__
        return result

    result["helper_exit_code"] = process.returncode
    result["helper_error"] = _safe_helper_error(stderr, uuid)

    payload = _parse_helper_stdout(stdout)
    if payload is None:
        result["result"] = "helper_invalid_output"
        return result

    result["native"] = payload
    if process.returncode not in (0, None):
        result["result"] = "helper_failed"
    elif payload.get("rdt_connected") is True:
        result["result"] = "rdt_connected"
    elif payload.get("iotc_connected") is True:
        result["result"] = "iotc_connected"
    elif payload.get("library_loaded") is True:
        result["result"] = "library_loaded"
    else:
        result["result"] = "native_probe_failed"
    return result
