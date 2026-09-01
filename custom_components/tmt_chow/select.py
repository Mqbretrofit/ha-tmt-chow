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
from .parameters import PARAMETERS, P710U_FUNCTIONS, ParameterDefinition


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]

    if hub.controller_type == "PS22087B" and hub.function_values:
        async_add_entities(
            TmtP710UFunctionSelect(hub, key)
            for key in hub.function_values
        )
        return

    if hub.supports_parameter_writes:
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


class TmtP710UFunctionSelect(TmtChowEntity, SelectEntity):
    """One P710U/PS22087B function returned by READ FUNCTION."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TmtChowHub, key: str) -> None:
        super().__init__(hub)
        self._key = key.upper()
        profile = P710U_FUNCTIONS.get(self._key)
        self._profile = profile

        self._attr_unique_id = f"{hub.uuid}_p710u_function_{self._key.lower()}"
        self._attr_name = (
            profile[0] if profile is not None else f"P710U function {self._key}"
        )

        current = hub.function_values.get(self._key)
        if profile is not None:
            self._value_to_label = dict(profile[1])
        elif current is not None:
            # Undocumented/reserved P710U functions are deliberately read-only.
            self._value_to_label = {current: f"Raw value {current}"}
        else:
            self._value_to_label = {}

        self._label_to_value = {
            label: value for value, label in self._value_to_label.items()
        }
        self._attr_options = list(self._label_to_value)

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self._key in self.hub.function_values
            and bool(self._attr_options)
        )

    @property
    def current_option(self) -> str | None:
        value = self.hub.function_values.get(self._key)
        if value is None:
            return None
        label = self._value_to_label.get(value)
        if label is not None:
            return label

        # Preserve visibility of an unexpected value without allowing it to be
        # written back as a guessed option.
        return f"Raw value {value}"

    async def async_select_option(self, option: str) -> None:
        if self._profile is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            )
        value = self._label_to_value.get(option)
        if value is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            )
        try:
            await self.hub.async_set_function(self._key, value)
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
