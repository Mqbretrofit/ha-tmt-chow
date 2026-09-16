"""Command buttons for TMT Chow gate controllers."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, OURANOS_POLLERS_DATA_KEY
from .entity import TmtChowEntity
from .hub import TmtChowHub, TmtCommandError
from .ouranos_status import OuranosStatusPoller
from .pedestrian import PEDESTRIAN_STRATEGY_NONE, pedestrian_strategy_for


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []
    if (
        pedestrian_strategy_for(hub.controller_type, hub.controller_capabilities)
        != PEDESTRIAN_STRATEGY_NONE
    ):
        entities.append(TmtPedestrianOpenButton(hub))
    poller: OuranosStatusPoller | None = hass.data.get(
        OURANOS_POLLERS_DATA_KEY, {}
    ).get(entry.entry_id)
    if poller is not None:
        entities.append(TmtOuranosRefreshButton(hub, poller))
    if entities:
        async_add_entities(entities)


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
            and pedestrian_strategy_for(
                self.hub.controller_type,
                self.hub.controller_capabilities,
            )
            != PEDESTRIAN_STRATEGY_NONE
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


class TmtOuranosRefreshButton(TmtChowEntity, ButtonEntity):
    """Request one immediate read-only native PS19001 status refresh."""

    _attr_translation_key = "ouranos_status_refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, hub: TmtChowHub, poller: OuranosStatusPoller) -> None:
        super().__init__(hub)
        self._poller = poller
        self._attr_unique_id = f"{hub.uuid}_ouranos_status_refresh"

    @property
    def available(self) -> bool:
        """Keep manual recovery available even when the cover is unavailable."""
        return True

    async def async_press(self) -> None:
        """Run one immediate status-only refresh."""
        if not await self._poller.async_refresh_once():
            raise HomeAssistantError(
                f"Native status refresh ended with {self._poller.last_result}"
            )
