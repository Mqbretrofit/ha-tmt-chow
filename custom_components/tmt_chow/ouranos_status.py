"""Native status polling for confirmed PS19001 gates."""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
    """Periodically read status through the shared native PS19001 session."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: TmtChowHub,
        pin_code: str,
        *,
        interval: float = OURANOS_STATUS_POLL_SECONDS,
        session: OuranosNativeSession | None = None,
    ) -> None:
        self._hass = hass
        self._hub = hub
        self._pin_code = pin_code
        self._interval = interval
        self._session = session or OuranosNativeSession(hass, hub.uuid, pin_code)
        self._hub.set_ouranos_native_session(self._session)
        self._refresh_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.last_result: str | None = None
        self.last_attempt_at: str | None = None
        self.last_success_at: str | None = None
        self.consecutive_failures = 0

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
        self._hub.set_ouranos_native_session(None)

    async def async_refresh_once(self) -> bool:
        """Read and apply one native gate status."""
        async with self._refresh_lock:
            self.last_attempt_at = datetime.now(UTC).isoformat()
            result: dict[str, Any] = await self._session.async_read_status()
            self.last_result = str(result.get("result") or "unknown")
            if self.last_result != "status_response_received":
                self.consecutive_failures += 1
                _LOGGER.debug(
                    "PS19001 native status read for %s ended with %s",
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
            if not self._hub.apply_ouranos_status_response(response):
                self.last_result = "invalid_status_response"
                self.consecutive_failures += 1
                self._hub.notify_ouranos_status_failure()
                return False
            self.consecutive_failures = 0
            self.last_success_at = datetime.now(UTC).isoformat()
            return True

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
                    "Unexpected PS19001 native status read failure for %s",
                    self._hub.name,
                )
                succeeded = False
            delay = self._interval if succeeded else max(
                self._interval, OURANOS_STATUS_FAILURE_RETRY_SECONDS
            )
            await asyncio.sleep(delay)
