"""Opt-in read-only native status polling for confirmed PS19001 gates."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import OURANOS_STATUS_POLL_SECONDS
from .hub import TmtChowHub
from .ouranos_ha_probe import async_probe_ouranos_on_ha

_LOGGER = logging.getLogger(__name__)
_FAILURE_RETRY_SECONDS = 30


class OuranosStatusPoller:
    """Periodically run the isolated PS19001 status-only helper."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: TmtChowHub,
        pin_code: str,
        *,
        interval: float = OURANOS_STATUS_POLL_SECONDS,
    ) -> None:
        self._hass = hass
        self._hub = hub
        self._pin_code = pin_code
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self.last_result: str | None = None

    async def async_start(self) -> None:
        """Start polling without delaying integration setup."""
        if self._task is None:
            self._task = asyncio.create_task(self._async_poll_loop())

    async def async_stop(self) -> None:
        """Stop polling and the currently running isolated helper, if any."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def async_refresh_once(self) -> bool:
        """Read and apply one native gate status."""
        result: dict[str, Any] = await async_probe_ouranos_on_ha(
            self._hass, self._hub.uuid, self._pin_code
        )
        self.last_result = str(result.get("result") or "unknown")
        if self.last_result != "status_response_received":
            _LOGGER.debug(
                "PS19001 native status read for %s ended with %s",
                self._hub.name,
                self.last_result,
            )
            self._hub.notify_ouranos_status_failure()
            return False

        native = result.get("native")
        response = native.get("status_response") if isinstance(native, dict) else None
        if not isinstance(response, str):
            self.last_result = "missing_status_response"
            self._hub.notify_ouranos_status_failure()
            return False
        if not self._hub.apply_ouranos_status_response(response):
            self.last_result = "invalid_status_response"
            self._hub.notify_ouranos_status_failure()
            return False
        return True

    async def _async_poll_loop(self) -> None:
        while True:
            try:
                succeeded = await self.async_refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep later read attempts alive
                self.last_result = "unexpected_error"
                self._hub.notify_ouranos_status_failure()
                _LOGGER.exception(
                    "Unexpected PS19001 native status read failure for %s",
                    self._hub.name,
                )
                succeeded = False
            delay = self._interval if succeeded else max(
                self._interval, _FAILURE_RETRY_SECONDS
            )
            await asyncio.sleep(delay)
