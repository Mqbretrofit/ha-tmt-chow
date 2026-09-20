"""Home Assistant-hosted read-only OURANOS/TUTK status probe.

The native TUTK library is never loaded into the Home Assistant Core process.
On x86_64 HAOS, where Core uses musl, the probe launches a tiny bundled glibc
helper through a private integrity-checked glibc loader/runtime. This avoids
relying on the host's missing ``ld-linux-x86-64.so.2`` and keeps native crashes
isolated from Home Assistant.

The helper sends exactly one allowlisted APK-compatible status request. The
legacy verified path uses ``READ STATUS``; a caller may explicitly select the
read-only ``RS`` status request for vendor UART V3.0 AutoProduct evidence. It
cannot accept arbitrary commands and never sends gate, parameter-read, or
parameter-write commands.
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

_TUTK_SDK_REPOSITORY: Final = "Soldier-Sen/tutk"
_TUTK_SDK_COMMIT: Final = "8a93626da7c12c936d550750e887a020c3049dc0"
_TUTK_SDK_PATH: Final = "Lib/Linux/x64/tmp_so"
_TUTK_SDK_BASE_URL: Final = (
    f"https://raw.githubusercontent.com/{_TUTK_SDK_REPOSITORY}/"
    f"{_TUTK_SDK_COMMIT}/{_TUTK_SDK_PATH}"
)
_TUTK_LIBRARY_FILES: Final[dict[str, tuple[str, str]]] = {
    "iotc": (
        "libIOTCAPIs.so",
        "bf92a8f33f6a69f9c40f5d1a825e993763bc614a0e364112d325e32ec01de843",
    ),
    "rdt": (
        "libRDTAPIs.so",
        "739575ad864b0e76c7fe89546e55e08e5ff8e63c36a95e08e5e744a607362296",
    ),
}
_SUPPORTED_MACHINES: Final = frozenset({"x86_64", "amd64", *ARM64_MACHINES})
_TMT_APK_IOTC_VERSION: Final = "0x03010521"
_PROBE_IOTC_VERSION: Final = "0x03010526"
_PROBE_RDT_VERSION: Final = "0x03010526"
_STATUS_COMMAND_MODES: Final = frozenset({"READ_STATUS", "RS"})
_MAX_TUTK_LIBRARY_BYTES: Final = 2 * 1024 * 1024
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
_MAX_GLIBC_BUNDLE_BYTES: Final = 64 * 1024 * 1024
_GLIBC_HELPER_SHA256: Final = (
    "72bf1dc3616f13eb1b941a646ca6db2a02efc40eb01020132fd0ea40d38419ff"
)


def _normalize_status_command(status_command: str) -> str:
    return status_command.strip().upper().replace(" ", "_")


def _base_result(uuid: str, status_command: str = "READ_STATUS") -> dict[str, Any]:
    machine = platform.machine().lower()
    mode = _normalize_status_command(status_command)
    arm64 = is_arm64_machine(machine)
    arm64_metadata: dict[str, Any] = {}
    if arm64:
        try:
            arm64_metadata = arm64_source_metadata()
        except RuntimeError:
            arm64_metadata = {}
    return {
        "result": "not_run",
        "applicable": len(uuid) == 20,
        "status_command_mode": mode,
        "status_command": "RS" if mode == "RS" else "READ STATUS",
        "home_assistant_machine": machine,
        "home_assistant_platform": sys.platform,
        "library_source_repository": (
            arm64_metadata.get("repository") if arm64 else _TUTK_SDK_REPOSITORY
        ),
        "library_source_commit": (
            arm64_metadata.get("commit") if arm64 else _TUTK_SDK_COMMIT
        ),
        "library_source_path": (
            arm64_metadata.get("path") if arm64 else _TUTK_SDK_PATH
        ),
        "library_source_abi": arm64_metadata.get("abi") if arm64 else "linux-x86_64",
        "library_architecture_supported": machine in _SUPPORTED_MACHINES,
        "library_downloaded": False,
        "library_integrity_verified": False,
        "iotc_library_integrity_verified": False,
        "rdt_library_integrity_verified": False,
        "tmt_apk_iotc_version": _TMT_APK_IOTC_VERSION,
        "probe_iotc_version_expected": (
            None if arm64 else _PROBE_IOTC_VERSION
        ),
        "probe_rdt_version_expected": (
            None if arm64 else _PROBE_RDT_VERSION
        ),
        "helper_runtime": (
            "private_bionic" if arm64 else "private_glibc"
        ) if machine in _SUPPORTED_MACHINES else None,
        "native_runtime_downloaded": False,
        "native_runtime_integrity_verified": False,
        "native_helper_integrity_verified": False,
        "glibc_version": (
            _GLIBC_VERSION if machine in {"x86_64", "amd64"} else None
        ),
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


def _safe_install_tutk_libraries(payloads: dict[str, bytes], target: Path) -> None:
    """Verify and install only the two pinned x86-64 TUTK libraries."""
    staging = target.with_name(target.name + ".tmp")
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    if set(payloads) != set(_TUTK_LIBRARY_FILES):
        raise RuntimeError("tutk_library_set_invalid")
    for library_name, (filename, expected_sha) in _TUTK_LIBRARY_FILES.items():
        payload = payloads[library_name]
        if not payload or len(payload) > _MAX_TUTK_LIBRARY_BYTES:
            raise RuntimeError(f"tutk_library_size_invalid:{library_name}")
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_sha:
            raise RuntimeError(
                f"tutk_library_integrity_failed:{library_name}:"
                f"expected={expected_sha}:actual={actual}"
            )
        output = staging / filename
        output.write_bytes(payload)
        os.chmod(output, 0o700)
    (staging / ".source-commit").write_text(_TUTK_SDK_COMMIT, encoding="ascii")
    if target.exists():
        import shutil
        shutil.rmtree(target)
    os.replace(staging, target)


async def _async_ensure_libraries(hass: HomeAssistant) -> tuple[Path, Path, bool]:
    if is_arm64_machine():
        return await async_ensure_arm64_libraries(hass)

    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(lambda: cache_dir.mkdir(parents=True, exist_ok=True))
    target = cache_dir / "tutk-3.1.5.38-x64"
    iotc = target / "libIOTCAPIs.so"
    rdt = target / "libRDTAPIs.so"
    marker = target / ".source-commit"

    def existing_ok() -> bool:
        try:
            return (
                marker.read_text(encoding="ascii").strip() == _TUTK_SDK_COMMIT
                and hashlib.sha256(iotc.read_bytes()).hexdigest()
                == _TUTK_LIBRARY_FILES["iotc"][1]
                and hashlib.sha256(rdt.read_bytes()).hexdigest()
                == _TUTK_LIBRARY_FILES["rdt"][1]
            )
        except OSError:
            return False

    if await hass.async_add_executor_job(existing_ok):
        return iotc, rdt, False

    library_names = tuple(_TUTK_LIBRARY_FILES)
    downloads = await asyncio.gather(
        *(
            _async_download(
                hass,
                f"{_TUTK_SDK_BASE_URL}/{_TUTK_LIBRARY_FILES[name][0]}",
                _MAX_TUTK_LIBRARY_BYTES,
            )
            for name in library_names
        )
    )
    payloads = dict(zip(library_names, downloads, strict=True))
    await hass.async_add_executor_job(_safe_install_tutk_libraries, payloads, target)
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


def _safe_helper_error(stderr: bytes, uuid: str, pin_code: str) -> str | None:
    text = stderr.decode("utf-8", "replace")
    text = (
        text.replace(uuid, "<redacted-uid>")
        .replace(pin_code, "<redacted-pin>")
        .strip()
    )
    return text[-1000:] if text else None


async def _async_run_process(
    argv: list[str],
    uuid: str,
    pin_code: str,
    status_command: str = "READ_STATUS",
    *,
    env: dict[str, str] | None = None,
) -> tuple[asyncio.subprocess.Process, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdin_payload = f"{uuid}\n{pin_code}\n{status_command}\n".encode("ascii")
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_payload),
            timeout=_HELPER_TIMEOUT,
        )
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process, stdout, stderr


async def async_probe_ouranos_on_ha(
    hass: HomeAssistant,
    uuid: str,
    pin_code: str,
    status_command: str = "READ_STATUS",
) -> dict[str, Any]:
    mode = _normalize_status_command(status_command)
    result = _base_result(uuid, mode)
    if mode not in _STATUS_COMMAND_MODES:
        result["result"] = "invalid_status_command"
        return result
    if len(uuid) != 20:
        result["result"] = "not_applicable"
        return result
    if len(pin_code) != 6 or any(char < "0" or char > "9" for char in pin_code):
        result["result"] = "invalid_pin"
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
        if is_arm64_machine(machine):
            (
                loader,
                libdir,
                helper,
                _session_helper,
                native_runtime_installed,
            ) = await async_ensure_arm64_runtime(hass)
            result["native_runtime_downloaded"] = native_runtime_installed
            result["native_runtime_integrity_verified"] = True
            result["native_helper_integrity_verified"] = True
            library_path = f"{libdir}:{iotc_path.parent}"
        else:
            loader, libdir, glibc_downloaded = await _async_ensure_glibc_runtime(hass)
            result["glibc_runtime_downloaded"] = glibc_downloaded
            result["glibc_runtime_integrity_verified"] = True
            helper = await hass.async_add_executor_job(_verify_bundled_glibc_helper)
            result["glibc_helper_integrity_verified"] = True
            result["native_runtime_downloaded"] = glibc_downloaded
            result["native_runtime_integrity_verified"] = True
            result["native_helper_integrity_verified"] = True
            library_path = str(libdir)

        if is_arm64_machine(machine):
            argv = [
                str(loader),
                str(helper),
                str(iotc_path),
                str(rdt_path),
            ]
        else:
            argv = [
                str(loader),
                "--library-path",
                library_path,
                str(helper),
                str(iotc_path),
                str(rdt_path),
            ]
        env = {**os.environ, "LD_LIBRARY_PATH": library_path}

        process, stdout, stderr = await _async_run_process(
            argv, uuid, pin_code, mode, env=env
        )
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
    result["helper_error"] = _safe_helper_error(stderr, uuid, pin_code)

    payload = _parse_helper_stdout(stdout)
    if payload is None:
        result["result"] = "helper_invalid_output"
        return result

    result["native"] = payload
    native_safety = payload.get("safety")
    if isinstance(native_safety, dict):
        for key in result["safety"]:
            if key in native_safety:
                result["safety"][key] = native_safety[key] is True
    if process.returncode not in (0, None):
        result["result"] = "helper_failed"
    elif payload.get("status_response_received") is True:
        result["result"] = "status_response_received"
    elif payload.get("status_request_sent") is True:
        result["result"] = "status_request_sent"
    elif payload.get("rdt_connected") is True:
        result["result"] = "rdt_connected"
    elif payload.get("iotc_connected") is True:
        result["result"] = "iotc_connected"
    elif payload.get("library_loaded") is True:
        result["result"] = "library_loaded"
    else:
        result["result"] = "native_probe_failed"
    return result
