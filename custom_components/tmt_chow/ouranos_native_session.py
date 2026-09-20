"""Persistent, allowlisted native IOTC/RDT session for verified controllers."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Final

from homeassistant.core import HomeAssistant

from .ouranos_arm64 import async_ensure_arm64_libraries, async_ensure_arm64_runtime, is_arm64_machine
from .ouranos_ha_probe import (
    _SUPPORTED_MACHINES,
    _async_ensure_glibc_runtime,
    _async_ensure_libraries,
)

_SESSION_HELPER_SHA256: Final = (
    "7b85b580f9e40b8bff3e3814e006e8b66b77efdf34ee980d7015b4df3cd64f06"
)
_SESSION_START_TIMEOUT: Final = 40
_RESPONSE_TIMEOUT: Final = 8
_SESSION_STOP_TIMEOUT: Final = 6
_PS19001_PARAMETER_FRAGMENT_RE: Final = re.compile(
    "".join(rf",{field_id}:[0-9A-Z]+" for field_id in "123456789ABCDEFGHIJ")
    + r"\Z"
)
_PS17062_PARAMETER_FRAGMENT_RE: Final = re.compile(
    "".join(
        rf",{field_id}:[0-9A-Z]+"
        for field_id in "0123456789ABCDEFGHIJKLM"
    )
    + r"\Z"
)
_PS25142_PARAMETER_BODY_RE: Final = re.compile(
    r"\d+(?:,\d+){17}\Z"
)


def _verify_bundled_session_helper() -> Path:
    helper = Path(__file__).with_name("native") / "ouranos_glibc_session_helper.amd64"
    try:
        data = helper.read_bytes()
    except OSError as err:
        raise RuntimeError("session_helper_missing") from err
    actual = hashlib.sha256(data).hexdigest()
    if actual != _SESSION_HELPER_SHA256:
        raise RuntimeError(
            "session_helper_integrity_failed:"
            f"expected={_SESSION_HELPER_SHA256}:actual={actual}"
        )
    return helper


class OuranosNativeSession:
    """Own one long-lived IOTC/RDT helper with a strict command allowlist."""

    def __init__(self, hass: HomeAssistant, uuid: str, pin_code: str) -> None:
        self._hass = hass
        self._uuid = uuid
        self._pin_code = pin_code
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr = ""

    @property
    def connected(self) -> bool:
        """Return whether the persistent helper is currently alive."""
        return self._process is not None and self._process.returncode is None

    async def async_read_status(
        self, status_command: str = "READ_STATUS"
    ) -> dict[str, Any]:
        """Request one allowlisted status response over the native connection."""
        mode = str(status_command or "READ_STATUS").strip().upper()
        protocol = {
            "READ_STATUS": "STATUS",
            "READ STATUS": "STATUS",
            "RS": "STATUS_RS",
        }.get(mode)
        if protocol is None:
            return {"result": "unsupported_status_command", "native": None}
        return await self._async_exchange(protocol, "status")

    async def async_gate_command(self, command: str) -> dict[str, Any]:
        """Send one fixed movement command; arbitrary wire commands are rejected."""
        protocol = {
            "FULL OPEN": "OPEN",
            "FULL CLOSE": "CLOSE",
            "STOP": "STOP",
            "PED OPEN": "PED",
        }.get(command)
        if protocol is None:
            return {"result": "unsupported_command", "native": None}
        return await self._async_exchange(protocol, "command")

    async def async_read_parameters(
        self, parameter_command: str = "READ FUNCTION"
    ) -> dict[str, Any]:
        """Read one complete allowlisted parameter frame."""
        mode = str(parameter_command or "READ FUNCTION").strip().upper()
        protocol = {
            "READ FUNCTION": "PARAM_READ",
            "RP,1": "PARAM_READ_V3",
        }.get(mode)
        if protocol is None:
            return {"result": "unsupported_parameter_command", "native": None}
        return await self._async_exchange(protocol, "parameter_read")

    async def async_write_parameters(self, command: str) -> dict[str, Any]:
        """Write one codec-validated complete parameter frame."""
        if command.startswith("WRITE FUNCTION"):
            fragment = command[len("WRITE FUNCTION") :]
            if _PS19001_PARAMETER_FRAGMENT_RE.fullmatch(fragment) is not None:
                protocol = f"PARAM_WRITE {fragment}"
            elif _PS17062_PARAMETER_FRAGMENT_RE.fullmatch(fragment) is not None:
                protocol = f"PARAM_WRITE_PS17062 {fragment}"
            else:
                return {"result": "invalid_parameter_command", "native": None}
        elif command.startswith("WP,1:"):
            body = command[len("WP,1:") :]
            if _PS25142_PARAMETER_BODY_RE.fullmatch(body) is None:
                return {"result": "invalid_parameter_command", "native": None}
            protocol = f"PARAM_WRITE_V3 {body}"
        else:
            return {"result": "unsupported_command", "native": None}
        return await self._async_exchange(protocol, "parameter_write")

    async def _async_exchange(
        self, protocol_command: str, event: str
    ) -> dict[str, Any]:
        """Run exactly one allowlisted exchange over the persistent session."""
        async with self._lock:
            start_error = await self._async_ensure_started_unlocked()
            if start_error is not None:
                return {"result": start_error, "native": None}

            process = self._process
            assert process is not None
            assert process.stdin is not None
            assert process.stdout is not None
            try:
                process.stdin.write((protocol_command + "\n").encode("ascii"))
                await process.stdin.drain()
                line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=_RESPONSE_TIMEOUT
                )
            except asyncio.CancelledError:
                await self._async_stop_unlocked()
                raise
            except (TimeoutError, BrokenPipeError, ConnectionError):
                await self._async_stop_unlocked()
                return {"result": "session_exchange_timeout", "native": None}

            payload = self._parse_line(line)
            if payload is None or payload.get("event") != event:
                await self._async_stop_unlocked()
                return {"result": "session_invalid_output", "native": None}
            if payload.get("transport_alive") is not True:
                await self._async_stop_unlocked()

            if payload.get("response_received") is True:
                result = f"{event}_response_received"
            elif payload.get("request_sent") is True:
                result = f"{event}_request_sent"
            else:
                result = "session_transport_failed"
            return {"result": result, "native": payload}

    async def async_stop(self) -> None:
        """Close the native session and release its helper process."""
        async with self._lock:
            await self._async_stop_unlocked()

    async def _async_ensure_started_unlocked(self) -> str | None:
        if self.connected:
            return None
        await self._async_stop_unlocked()

        if len(self._uuid) != 20:
            return "not_applicable"
        if (
            len(self._pin_code) != 6
            or not self._pin_code.isascii()
            or not self._pin_code.isdigit()
        ):
            return "invalid_pin"
        if platform.machine().lower() not in _SUPPORTED_MACHINES:
            return "unsupported_architecture"

        try:
            if is_arm64_machine():
                iotc_path, rdt_path, _ = await async_ensure_arm64_libraries(self._hass)
                (
                    loader,
                    libdir,
                    _probe_helper,
                    helper,
                    _runtime_installed,
                ) = await async_ensure_arm64_runtime(self._hass)
                library_path = f"{libdir}:{iotc_path.parent}"
            else:
                iotc_path, rdt_path, _ = await _async_ensure_libraries(self._hass)
                loader, libdir, _ = await _async_ensure_glibc_runtime(self._hass)
                helper = await self._hass.async_add_executor_job(
                    _verify_bundled_session_helper
                )
                library_path = str(libdir)
            env = {**os.environ, "LD_LIBRARY_PATH": library_path}
            if is_arm64_machine():
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
            self._process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            process = self._process
            assert process.stdin is not None
            assert process.stdout is not None
            self._stderr_task = asyncio.create_task(self._async_drain_stderr(process))
            process.stdin.write(
                (self._uuid + "\n" + self._pin_code + "\n").encode("ascii")
            )
            await process.stdin.drain()
            line = await asyncio.wait_for(
                process.stdout.readline(), timeout=_SESSION_START_TIMEOUT
            )
        except asyncio.CancelledError:
            await self._async_stop_unlocked()
            raise
        except TimeoutError:
            await self._async_stop_unlocked()
            return "session_connect_timeout"
        except RuntimeError as err:
            await self._async_stop_unlocked()
            return self._safe_reason(str(err), "session_runtime_unavailable")
        except Exception as err:  # noqa: BLE001 - native process boundary
            await self._async_stop_unlocked()
            return f"session_start_failed:{type(err).__name__}"

        ready = self._parse_line(line)
        if ready is None or ready.get("event") != "ready":
            await self._async_stop_unlocked()
            return "session_invalid_ready"
        if ready.get("connected") is not True:
            stage = str(ready.get("stage") or "unknown")
            code = ready.get("code")
            await self._async_stop_unlocked()
            return self._safe_reason(
                f"session_connect_failed:{stage}:{code}", "session_connect_failed"
            )
        return None

    async def _async_stop_unlocked(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                with contextlib.suppress(BrokenPipeError, ConnectionError):
                    process.stdin.write(b"QUIT\n")
                    await process.stdin.drain()
            try:
                await asyncio.wait_for(process.wait(), timeout=_SESSION_STOP_TIMEOUT)
            except TimeoutError:
                process.kill()
                await process.wait()
        task = self._stderr_task
        self._stderr_task = None
        if task is not None:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _async_drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while chunk := await process.stderr.read(1024):
            text = chunk.decode("utf-8", "replace")
            self._stderr = self._safe_reason(text, "")[-1000:]

    def _safe_reason(self, value: str, fallback: str) -> str:
        safe = value.replace(self._uuid, "<redacted-uid>").replace(
            self._pin_code, "<redacted-pin>"
        )
        return safe[-1000:] if safe else fallback

    @staticmethod
    def _parse_line(line: bytes) -> dict[str, Any] | None:
        if not line:
            return None
        try:
            payload = json.loads(line.decode("utf-8", "replace"))
        except (UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
