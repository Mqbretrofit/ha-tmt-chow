"""Native status polling for verified OURANOS gate routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    OURANOS_STATUS_FAILURE_RETRY_SECONDS,
    OURANOS_STATUS_POLL_SECONDS,
)
from .hub import TmtChowHub
from .ouranos_native_session import OuranosNativeSession

_LOGGER = logging.getLogger(__name__)


class OuranosStatusPoller:
    """Periodically read status through a verified native OURANOS session."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: TmtChowHub,
        pin_code: str,
        *,
        interval: float = OURANOS_STATUS_POLL_SECONDS,
        session: OuranosNativeSession | None = None,
        status_command: str = "READ_STATUS",
        expose_control_session: bool = True,
    ) -> None:
        self._hass = hass
        self._hub = hub
        self._pin_code = pin_code
        self._interval = interval
        self._status_command = status_command
        self._expose_control_session = expose_control_session
        self._session = session or OuranosNativeSession(hass, hub.uuid, pin_code)
        if expose_control_session:
            self._hub.set_ouranos_native_session(self._session)
        self._refresh_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.last_result: str | None = None
        self.last_attempt_at: str | None = None
        self.last_success_at: str | None = None
        self.consecutive_failures = 0
        self.last_movement_test: dict[str, Any] | None = None

    async def async_start(self) -> None:
        """Start polling without delaying integration setup."""
        if self._task is None:
            self._task = asyncio.create_task(self._async_poll_loop())

    async def async_stop(self) -> None:
        """Stop polling and the currently running isolated helper, if any."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._session.async_stop()
        if self._expose_control_session:
            self._hub.set_ouranos_native_session(None)

    async def async_refresh_once(self) -> bool:
        """Read and apply one native gate status."""
        async with self._refresh_lock:
            self.last_attempt_at = datetime.now(UTC).isoformat()
            result: dict[str, Any] = await self._session.async_read_status(
                self._status_command
            )
            self.last_result = str(result.get("result") or "unknown")
            if self.last_result != "status_response_received":
                self.consecutive_failures += 1
                _LOGGER.debug(
                    "OURANOS native status read for %s ended with %s",
                    self._hub.name,
                    self.last_result,
                )
                self._hub.notify_ouranos_status_failure()
                return False

            native = result.get("native")
            response = native.get("response") if isinstance(native, dict) else None
            if not isinstance(response, str):
                self.last_result = "missing_status_response"
                self.consecutive_failures += 1
                self._hub.notify_ouranos_status_failure()
                return False
            if not self._hub.apply_ouranos_status_response(
                response, status_command=self._status_command
            ):
                self.last_result = "invalid_status_response"
                self.consecutive_failures += 1
                self._hub.notify_ouranos_status_failure()
                return False
            self.consecutive_failures = 0
            self.last_success_at = datetime.now(UTC).isoformat()
            return True

    async def async_movement_test(self, action: str) -> dict[str, Any]:
        """Send exactly one guarded PS25142 movement test command.

        This remains an explicit diagnostic action even on profiles whose normal
        cover controls are enabled. The caller must already have a fresh verified
        status, and OPEN/CLOSE are only allowed
        from their opposite stopped end positions.  STOP is only allowed while
        movement is currently reported.  A movement command is never retried.
        """
        normalized = str(action or "").strip().lower()
        wire_command = {
            "open": "FULL OPEN",
            "close": "FULL CLOSE",
            "stop": "STOP",
        }.get(normalized)
        if wire_command is None:
            result = {
                "result": "invalid_action",
                "action": normalized,
                "movement_command_sent": False,
                "automatic_retry": False,
            }
            self.last_movement_test = result
            return result

        async with self._refresh_lock:
            before = {
                "position": self._hub.position,
                "movement": self._hub.movement,
                "is_operating": self._hub.is_operating,
            }
            blocker: str | None = None
            if not self._hub.ouranos_status_available:
                blocker = "fresh_native_status_required"
            elif normalized == "open" and not (
                self._hub.position == 0 and self._hub.is_operating is False
            ):
                blocker = "open_requires_fully_closed_stopped_gate"
            elif normalized == "close" and not (
                self._hub.position == 100 and self._hub.is_operating is False
            ):
                blocker = "close_requires_fully_open_stopped_gate"
            elif normalized == "stop" and self._hub.is_operating is not True:
                blocker = "stop_requires_gate_reported_moving"

            if blocker is not None:
                result = {
                    "result": "precondition_failed",
                    "action": normalized,
                    "wire_command": wire_command,
                    "blocker": blocker,
                    "before": before,
                    "movement_command_sent": False,
                    "automatic_retry": False,
                }
                self.last_movement_test = result
                return result

            command_result = await self._session.async_gate_command(wire_command)
            native = command_result.get("native")
            native_response = (
                native.get("response") if isinstance(native, dict) else None
            )
            safety = native.get("safety") if isinstance(native, dict) else None
            command_sent = bool(
                (
                    isinstance(safety, dict)
                    and safety.get("gate_command_sent") is True
                )
                or (
                    isinstance(native, dict)
                    and native.get("request_sent") is True
                )
            )
            acknowledged = (
                isinstance(native_response, str)
                and f"ACK {wire_command}" in native_response
            )
            rejected = (
                isinstance(native_response, str) and "NAK " in native_response
            )

            if normalized == "stop" and acknowledged:
                # Beta.32 proved ACK STOP stops the physical PS25142, but the
                # immediately following RS can still contain one stale moving
                # frame. Preserve the explicit STOP result while telemetry
                # settles; never resend STOP.
                self._hub.is_operating = False
                self._hub.movement = None
                self._hub._native_stop_guard_until_monotonic = (  # noqa: SLF001
                    time.monotonic() + 6.0
                )
                self._hub._notify()  # noqa: SLF001

            # One read-only RS refresh after the one-shot command.  This can
            # confirm motion even when the movement ACK itself is not returned.
            status_result: dict[str, Any] | None = None
            if command_sent:
                await asyncio.sleep(1.0)
                status_result = await self._session.async_read_status(
                    self._status_command
                )
                status_native = status_result.get("native")
                status_response = (
                    status_native.get("response")
                    if isinstance(status_native, dict)
                    else None
                )
                if (
                    status_result.get("result") == "status_response_received"
                    and isinstance(status_response, str)
                ):
                    if self._hub.apply_ouranos_status_response(
                        status_response, status_command=self._status_command
                    ):
                        self.last_result = "status_response_received"
                        self.last_attempt_at = datetime.now(UTC).isoformat()
                        self.last_success_at = self.last_attempt_at
                        self.consecutive_failures = 0

            after = {
                "position": self._hub.position,
                "movement": self._hub.movement,
                "is_operating": self._hub.is_operating,
            }
            telemetry_confirmed = (
                normalized == "open"
                and self._hub.is_operating is True
                and self._hub.movement == "opening"
            ) or (
                normalized == "close"
                and self._hub.is_operating is True
                and self._hub.movement == "closing"
            ) or (
                normalized == "stop"
                and self._hub.is_operating is False
            )

            outcome = (
                "rejected"
                if rejected
                else "acknowledged"
                if acknowledged
                else "telemetry_confirmed"
                if telemetry_confirmed
                else "sent_no_ack"
                if command_sent
                else "transport_failed"
            )
            result = {
                "result": outcome,
                "action": normalized,
                "wire_command": wire_command,
                "before": before,
                "after": after,
                "movement_command_sent": command_sent,
                "automatic_retry": False,
                "command_transport_result": command_result.get("result"),
                "command_response": native_response,
                "post_status_result": (
                    status_result.get("result")
                    if isinstance(status_result, dict)
                    else None
                ),
                "telemetry_confirmed": telemetry_confirmed,
            }
            self.last_movement_test = result
            return result

    @property
    def refresh_in_progress(self) -> bool:
        """Return whether a native refresh is currently running."""
        return self._refresh_lock.locked()

    @property
    def session_connected(self) -> bool:
        """Return whether the persistent native transport is alive."""
        return self._session.connected

    async def _async_poll_loop(self) -> None:
        while True:
            try:
                succeeded = await self.async_refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_result = "unexpected_error"
                self.consecutive_failures += 1
                self._hub.notify_ouranos_status_failure()
                _LOGGER.exception(
                    "Unexpected OURANOS native status read failure for %s",
                    self._hub.name,
                )
                succeeded = False
            delay = self._interval if succeeded else max(
                self._interval, OURANOS_STATUS_FAILURE_RETRY_SECONDS
            )
            await asyncio.sleep(delay)
