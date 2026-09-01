"""Shared TMT Chow entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .hub import TmtChowHub


class TmtChowEntity(Entity):
    """An entity backed by one TMT Chow hub."""

    _attr_has_entity_name = True

    def __init__(self, hub: TmtChowHub) -> None:
        self.hub = hub
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.uuid)},
            manufacturer="TMT Automation",
            model=hub.controller_type or hub.product_type or "Chow gate controller",
            name=hub.name,
        )

    @property
    def available(self) -> bool:
        return self.hub.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_listener(self.async_write_ha_state))
