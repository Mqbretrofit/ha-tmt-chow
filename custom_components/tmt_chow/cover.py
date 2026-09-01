"""Cover entity for a TMT Chow gate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller_types import is_known_non_gate_controller
from .entity import TmtChowEntity
from .hub import TmtChowHub, TmtCommandError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    if is_known_non_gate_controller(hub.controller_type):
        return
    async_add_entities([TmtChowCover(hub)])


class TmtChowCover(TmtChowEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.GATE
    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, hub: TmtChowHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = hub.uuid

    @property
    def current_cover_position(self) -> int | None:
        return self.hub.position

    @property
    def is_closed(self) -> bool | None:
        return None if self.hub.position is None else self.hub.position == 0

    @property
    def is_opening(self) -> bool:
        return self.hub.movement == "opening"

    @property
    def is_closing(self) -> bool:
        return self.hub.movement == "closing"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.hub.attributes

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._run(self.hub.async_open())

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._run(self.hub.async_close())

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._run(self.hub.async_stop_gate())

    async def _run(self, action: Any) -> None:
        try:
            await action
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
