"""TMT Chow parameter selectors."""

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
from .parameters import (
    PARAMETERS,
    P710U_PARAMETERS,
    P710UParameterDefinition,
    ParameterDefinition,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]

    if (
        hub.controller_type == "PS22087B"
        and hub.parameters is not None
        and len(hub.parameters) == len(P710U_PARAMETERS)
    ):
        async_add_entities(
            TmtP710UParameterSelect(hub, index, definition)
            for index, definition in enumerate(P710U_PARAMETERS)
        )
        return

    if hub.supports_parameter_writes:
        async_add_entities(
            TmtParameterSelect(hub, index, definition)
            for index, definition in enumerate(PARAMETERS)
        )


class TmtParameterSelect(TmtChowEntity, SelectEntity):
    """Verified PS21053/PS21053C parameter."""

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


class TmtP710UParameterSelect(TmtChowEntity, SelectEntity):
    """One P710U / PS22087B parameter from the 15-value RP,1 profile."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hub: TmtChowHub,
        index: int,
        definition: P710UParameterDefinition,
    ) -> None:
        super().__init__(hub)
        self._index = index
        self._definition = definition
        self._attr_unique_id = (
            f"{hub.uuid}_p710u_parameter_{definition.code.lower()}"
        )
        self._attr_name = f"{definition.code} – {definition.name}"

        current = (
            hub.parameters[index]
            if hub.parameters is not None and index < len(hub.parameters)
            else None
        )

        options = list(definition.options)
        if not definition.writable and current is not None:
            options = [f"Raw value {current}"]
        elif current is not None and not 0 <= current < len(options):
            options.append(f"Raw value {current}")
        self._attr_options = options

    @property
    def available(self) -> bool:
        values = self.hub.parameters
        return (
            self.hub.available
            and values is not None
            and len(values) == len(P710U_PARAMETERS)
            and self._index < len(values)
        )

    @property
    def current_option(self) -> str | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None

        value = values[self._index]
        if 0 <= value < len(self._definition.options):
            return self._definition.options[value]
        return f"Raw value {value}"

    async def async_select_option(self, option: str) -> None:
        if not self._definition.writable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            )

        try:
            value = self._definition.options.index(option)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err

        try:
            await self.hub.async_set_p710u_parameter(self._index, value)
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
