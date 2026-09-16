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
from pathlib import Path, PurePosixPath
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_WYZE_COMMIT: Final = "bf893749b748f142199c9bce14fac44f8a661d6e"
_LIBRARY_BASE: Final = (
    "https://raw.githubusercontent.com/mrlt8/docker-wyze-bridge/"
    f"{_WYZE_COMMIT}/app/lib/"
)
_MAX_LIBRARY_BYTES: Final = 8 * 1024 * 1024
_DOWNLOAD_TIMEOUT: Final = 45
_HELPER_TIMEOUT: Final = 40

_LIBRARY_SOURCES: Final[dict[str, tuple[str, str]]] = {
    "x86_64": ("lib.amd64", "99dbdf9f15f2d1c6eb926b7d1b67697e67a33a13"),
    "amd64": ("lib.amd64", "99dbdf9f15f2d1c6eb926b7d1b67697e67a33a13"),
    "aarch64": ("lib.arm64", "a3ff9de4300ed869c2ba9a589a1bd1bfede979b6"),
    "arm64": ("lib.arm64", "a3ff9de4300ed869c2ba9a589a1bd1bfede979b6"),
    "armv7l": ("lib.arm", "2fee47acb86ac1b853949467e63f5af689684540"),
    "armv7": ("lib.arm", "2fee47acb86ac1b853949467e63f5af689684540"),
}

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
    "401942e411fdde6727376ef0cb40e402c58b00fc1a9ef010223c53c388c948ec"
)


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _base_result(uuid: str) -> dict[str, Any]:
    machine = platform.machine().lower()
    return {
        "result": "not_run",
        "applicable": len(uuid) == 20,
        "home_assistant_machine": machine,
        "home_assistant_platform": sys.platform,
        "library_source_commit": _WYZE_COMMIT,
        "library_architecture_supported": machine in _LIBRARY_SOURCES,
        "library_downloaded": False,
        "library_integrity_verified": False,
        "helper_runtime": "private_glibc" if machine in {"x86_64", "amd64"} else "host_python",
        "glibc_version": _GLIBC_VERSION if machine in {"x86_64", "amd64"} else None,
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


async def _async_ensure_library(hass: HomeAssistant, machine: str) -> tuple[Path, bool]:
    source = _LIBRARY_SOURCES.get(machine)
    if source is None:
        raise RuntimeError(f"unsupported_machine:{machine}")
    filename, expected_blob_sha = source
    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(lambda: cache_dir.mkdir(parents=True, exist_ok=True))
    target = cache_dir / filename

    def existing_ok() -> bool:
        try:
            data = target.read_bytes()
        except OSError:
            return False
        return _git_blob_sha1(data) == expected_blob_sha

    if await hass.async_add_executor_job(existing_ok):
        return target, False

    data = await _async_download(hass, _LIBRARY_BASE + filename, _MAX_LIBRARY_BYTES)
    actual = _git_blob_sha1(data)
    if actual != expected_blob_sha:
        raise RuntimeError(
            f"library_integrity_failed:expected={expected_blob_sha}:actual={actual}"
        )

    temp = target.with_suffix(target.suffix + ".tmp")

    def store() -> None:
        temp.write_bytes(data)
        os.chmod(temp, 0o700)
        os.replace(temp, target)

    await hass.async_add_executor_job(store)
    return target, True


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
    if machine not in _LIBRARY_SOURCES:
        result["result"] = "unsupported_architecture"
        return result

    try:
        library_path, downloaded = await _async_ensure_library(hass, machine)
    except RuntimeError as err:
        result["result"] = "library_unavailable"
        result["helper_error"] = str(err)
        return result

    result["library_downloaded"] = downloaded
    result["library_integrity_verified"] = True

    process: asyncio.subprocess.Process | None = None
    try:
        if machine in {"x86_64", "amd64"}:
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
                str(library_path),
            ]
            env = {**os.environ, "LD_LIBRARY_PATH": str(libdir)}
        else:
            helper = Path(__file__).with_name("ouranos_native_helper.py")
            if not helper.is_file():
                result["result"] = "helper_missing"
                return result
            argv = [sys.executable, str(helper), str(library_path)]
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}

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
