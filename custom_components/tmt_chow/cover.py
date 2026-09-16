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
from .pedestrian import PEDESTRIAN_STRATEGY_NONE
from .pedestrian_state import (
    cancel_pedestrian_display_cycle,
    pedestrian_display_is_closed,
    pedestrian_display_movement,
    pedestrian_display_position,
)
from .pedestrian_state_v17 import process_pedestrian_display_telemetry


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

    async def async_added_to_hass(self) -> None:
        # Use a cover-specific listener so the pedestrian presentation machine
        # advances before Home Assistant reads the entity state for this update.
        self.async_on_remove(self.hub.add_listener(self._handle_hub_update))

    def _handle_hub_update(self) -> None:
        process_pedestrian_display_telemetry(self.hub)
        self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        return pedestrian_display_position(self.hub)

    @property
    def is_closed(self) -> bool | None:
        return pedestrian_display_is_closed(self.hub)

    @property
    def is_opening(self) -> bool:
        return pedestrian_display_movement(self.hub) == "opening"

    @property
    def is_closing(self) -> bool:
        return pedestrian_display_movement(self.hub) == "closing"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = dict(self.hub.attributes)
        pedestrian_strategy = self.hub.pedestrian_strategy
        if pedestrian_strategy != PEDESTRIAN_STRATEGY_NONE:
            attributes["tmt_chow_pedestrian_supported"] = True
            attributes["tmt_chow_pedestrian_uuid"] = self.hub.uuid
            attributes["tmt_chow_pedestrian_strategy"] = pedestrian_strategy
        return attributes

    async def async_open_cover(self, **kwargs: Any) -> None:
        cancel_pedestrian_display_cycle(self.hub)
        await self._run(self.hub.async_open())

    async def async_close_cover(self, **kwargs: Any) -> None:
        cancel_pedestrian_display_cycle(self.hub)
        await self._run(self.hub.async_close())

    async def async_stop_cover(self, **kwargs: Any) -> None:
        cancel_pedestrian_display_cycle(self.hub)
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
