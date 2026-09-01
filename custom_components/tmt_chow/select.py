"""Validated PS21053 parameter selectors."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TmtChowEntity
from .hub import TmtChowHub, TmtCommandError
from .parameters import PARAMETERS, ParameterDefinition


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    if not hub.supports_parameter_writes:
        return
    async_add_entities(
        TmtParameterSelect(hub, index, definition)
        for index, definition in enumerate(PARAMETERS)
    )


class TmtParameterSelect(TmtChowEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hub: TmtChowHub,
        index: int,
        definition: ParameterDefinition,
    ) -> None:
        super().__init__(hub)
        self._index = index
        self._definition = definition
        self._attr_unique_id = f"{hub.uuid}_parameter_{index + 1}"
        self._attr_translation_key = definition.key
        self._attr_options = list(definition.options)

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self.hub.supports_parameter_writes
            and self.hub.parameters is not None
        )

    @property
    def current_option(self) -> str | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None
        value = values[self._index]
        if not 0 <= value < len(self._definition.options):
            return None
        return self._definition.options[value]

    async def async_select_option(self, option: str) -> None:
        try:
            value = self._definition.options.index(option)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err
        try:
            await self.hub.async_set_parameter(self._index, value)
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
