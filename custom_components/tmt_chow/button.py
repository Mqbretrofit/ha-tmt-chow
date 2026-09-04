"""Command buttons for TMT Chow gate controllers."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller_types import CAPABILITY_PEDESTRIAN
from .entity import TmtChowEntity
from .hub import TmtChowHub, TmtCommandError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    if CAPABILITY_PEDESTRIAN not in hub.controller_capabilities:
        return
    async_add_entities([TmtPedestrianOpenButton(hub)])


class TmtPedestrianOpenButton(TmtChowEntity, ButtonEntity):
    """Open the gate to its configured pedestrian/partial position."""

    _attr_translation_key = "pedestrian_open"
    _attr_icon = "mdi:walk"

    def __init__(self, hub: TmtChowHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.uuid}_pedestrian_open"

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and CAPABILITY_PEDESTRIAN in self.hub.controller_capabilities
        )

    async def async_press(self) -> None:
        try:
            await self.hub.async_pedestrian_open()
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
