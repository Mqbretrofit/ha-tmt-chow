"""Home Assistant-hosted read-only OURANOS/TUTK transport probe.

The native library is never loaded into the Home Assistant process.  A pinned
architecture-matched helper library is downloaded into /config/.storage and is
executed by a short-lived child Python process.  A native crash therefore cannot
crash Home Assistant.

The probe is transport-only.  It never calls RDT_Write and never sends a gate,
status-read, parameter-read, or parameter-write command.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
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

# The SHA values are Git blob SHA-1 values from the pinned repository commit.
_LIBRARY_SOURCES: Final[dict[str, tuple[str, str]]] = {
    "x86_64": ("lib.amd64", "99dbdf9f15f2d1c6eb926b7d1b67697e67a33a13"),
    "amd64": ("lib.amd64", "99dbdf9f15f2d1c6eb926b7d1b67697e67a33a13"),
    "aarch64": ("lib.arm64", "a3ff9de4300ed869c2ba9a589a1bd1bfede979b6"),
    "arm64": ("lib.arm64", "a3ff9de4300ed869c2ba9a589a1bd1bfede979b6"),
    "armv7l": ("lib.arm", "2fee47acb86ac1b853949467e63f5af689684540"),
    "armv7": ("lib.arm", "2fee47acb86ac1b853949467e63f5af689684540"),
}


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


async def _async_ensure_library(hass: HomeAssistant, machine: str) -> tuple[Path, bool]:
    source = _LIBRARY_SOURCES.get(machine)
    if source is None:
        raise RuntimeError(f"unsupported_machine:{machine}")
    filename, expected_blob_sha = source
    cache_dir = Path(hass.config.path(".storage", "tmt_chow_ouranos"))
    await hass.async_add_executor_job(cache_dir.mkdir, parents=True, exist_ok=True)
    target = cache_dir / filename

    def existing_ok() -> bool:
        try:
            data = target.read_bytes()
        except OSError:
            return False
        return _git_blob_sha1(data) == expected_blob_sha

    if await hass.async_add_executor_job(existing_ok):
        return target, False

    session = async_get_clientsession(hass)
    url = _LIBRARY_BASE + filename
    try:
        async with asyncio.timeout(_DOWNLOAD_TIMEOUT):
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.read()
    except Exception as err:
        raise RuntimeError(f"library_download_failed:{type(err).__name__}") from err

    if not data or len(data) > _MAX_LIBRARY_BYTES:
        raise RuntimeError(f"library_size_invalid:{len(data)}")
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


async def async_probe_ouranos_on_ha(hass: HomeAssistant, uuid: str) -> dict[str, Any]:
    """Run the isolated read-only OURANOS native connectivity probe on HA."""
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

    helper = Path(__file__).with_name("ouranos_native_helper.py")
    if not helper.is_file():
        result["result"] = "helper_missing"
        return result

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(helper),
            str(library_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        result["helper_started"] = True
        stdout, stderr = await asyncio.wait_for(
            process.communicate((uuid + "\n").encode("ascii")),
            timeout=_HELPER_TIMEOUT,
        )
    except TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        result["result"] = "helper_timeout"
        result["helper_error"] = "native helper exceeded safety timeout"
        return result
    except Exception as err:
        result["result"] = "helper_start_failed"
        result["helper_error"] = type(err).__name__
        return result

    result["helper_exit_code"] = process.returncode
    stderr_text = stderr.decode("utf-8", "replace").strip()
    if stderr_text:
        # The helper is forbidden from printing the raw UID. Keep stderr bounded.
        result["helper_error"] = stderr_text[-1000:]

    try:
        payload = json.loads(stdout.decode("utf-8", "replace").strip())
    except (json.JSONDecodeError, UnicodeDecodeError):
        result["result"] = "helper_invalid_output"
        return result
    if not isinstance(payload, dict):
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
