"""Model-specific TMT Chow parameter selectors."""

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
from .model_parameter_schemas import parameter_name, parameter_options
from .parameter_codec import is_editable_parameter
from .parameters import PARAMETERS, ParameterDefinition
from .ps21050d_parameters import (
    CONTROLLER_TYPE as PS21050D,
    PS21050DParameterError,
    option_to_wire_value as ps21050d_option_to_wire_value,
    parameter_options_for as ps21050d_parameter_options,
    wire_value_to_option as ps21050d_wire_value_to_option,
)
from .ps22027_parameters import (
    CONTROLLER_TYPE as PS22027,
    PS22027ParameterError,
    option_to_wire_value as ps22027_option_to_wire_value,
    parameter_options_for as ps22027_parameter_options,
    wire_value_to_option as ps22027_wire_value_to_option,
)

_LEGACY_PS21053 = {"PS21053", "PS21053C"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    schema = hub.model_parameter_schema
    if not hub.supports_parameters or schema is None:
        return

    # Keep the existing PS21053 entity IDs, translation keys and stable option
    # keys exactly as they were before multi-model support was added.
    if hub.controller_type in _LEGACY_PS21053:
        async_add_entities(
            TmtParameterSelect(hub, index, definition)
            for index, definition in enumerate(PARAMETERS)
        )
        return

    # PS21050D is the live identity of the PS21050 app profile on the captured
    # hardware. Its two current fields switch option/offset tables when Motor
    # Type is Hall, so their options must be evaluated against the live frame.
    if hub.parameter_model_type == PS21050D:
        async_add_entities(
            TmtPS21050DParameterSelect(hub, index, spec)
            for index, spec in enumerate(schema)
            if is_editable_parameter(spec) and ps21050d_parameter_options(index)
        )
        return

    # PS22027 also uses mode-dependent current values. Live Hall-mode hardware
    # proved that the two current slots use the P190 Hall table with wire offset
    # 5, while the remaining 18 slots use the PS22027 app schema directly.
    if hub.parameter_model_type == PS22027:
        async_add_entities(
            TmtPS22027ParameterSelect(hub, index, spec)
            for index, spec in enumerate(schema)
            if is_editable_parameter(spec)
            and ps22027_parameter_options(index, hub.parameters)
        )
        return

    entities = []
    for index, spec in enumerate(schema):
        options = parameter_options(spec)
        if not is_editable_parameter(spec) or not options:
            continue
        entities.append(TmtModelParameterSelect(hub, index, spec))
    async_add_entities(entities)


class TmtParameterSelect(TmtChowEntity, SelectEntity):
    """Backward-compatible PS21053 selector."""

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
            and self.hub.supports_parameters
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
        await _async_set(self.hub, self._index, value)


class TmtPS21050DParameterSelect(TmtChowEntity, SelectEntity):
    """PS21050D selector backed by the app's exact 20-value wire frame."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TmtChowHub, index: int, spec: tuple) -> None:
        super().__init__(hub)
        self._index = index
        self._spec = spec
        self._attr_unique_id = f"{hub.uuid}_parameter_{index + 1}"
        self._attr_name = parameter_name(spec)

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self.hub.supports_parameters
            and self.hub.parameters is not None
        )

    @property
    def options(self) -> list[str]:
        return list(ps21050d_parameter_options(self._index, self.hub.parameters))

    @property
    def current_option(self) -> str | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None
        return ps21050d_wire_value_to_option(
            self._index,
            values[self._index],
            values,
        )

    async def async_select_option(self, option: str) -> None:
        values = self.hub.parameters
        if values is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="parameters_not_ready",
            )
        try:
            value = ps21050d_option_to_wire_value(self._index, option, values)
        except PS21050DParameterError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err
        await _async_set(self.hub, self._index, value)


class TmtPS22027ParameterSelect(TmtChowEntity, SelectEntity):
    """PS22027 selector backed by its verified 20-value RP,1/WP,1 frame."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TmtChowHub, index: int, spec: tuple) -> None:
        super().__init__(hub)
        self._index = index
        self._spec = spec
        self._attr_unique_id = f"{hub.uuid}_parameter_{index + 1}"
        self._attr_name = parameter_name(spec)

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self.hub.supports_parameters
            and self.hub.parameters is not None
        )

    @property
    def options(self) -> list[str]:
        return list(ps22027_parameter_options(self._index, self.hub.parameters))

    @property
    def current_option(self) -> str | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None
        return ps22027_wire_value_to_option(
            self._index,
            values[self._index],
            values,
        )

    async def async_select_option(self, option: str) -> None:
        values = self.hub.parameters
        if values is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="parameters_not_ready",
            )
        try:
            value = ps22027_option_to_wire_value(self._index, option, values)
        except PS22027ParameterError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err
        await _async_set(self.hub, self._index, value)


class TmtModelParameterSelect(TmtChowEntity, SelectEntity):
    """Discrete parameter selector generated from the vendor model schema."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TmtChowHub, index: int, spec: tuple) -> None:
        super().__init__(hub)
        self._index = index
        self._spec = spec
        self._options = tuple(parameter_options(spec))
        self._attr_unique_id = f"{hub.uuid}_parameter_{index + 1}"
        self._attr_name = parameter_name(spec)
        self._attr_options = list(self._options)

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self.hub.supports_parameters
            and self.hub.parameters is not None
        )

    @property
    def current_option(self) -> str | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None
        value = values[self._index]
        if not 0 <= value < len(self._options):
            return None
        return self._options[value]

    async def async_select_option(self, option: str) -> None:
        try:
            value = self._options.index(option)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err
        await _async_set(self.hub, self._index, value)


async def _async_set(hub: TmtChowHub, index: int, value: int) -> None:
    try:
        await hub.async_set_parameter(index, value)
    except TmtCommandError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=err.translation_key,
            translation_placeholders=err.translation_placeholders,
        ) from err
