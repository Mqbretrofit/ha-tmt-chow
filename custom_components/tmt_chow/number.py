"""Model-specific numeric TMT Chow parameters."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TmtChowEntity
from .hub import TmtChowHub, TmtCommandError
from .model_parameter_schemas import parameter_name, parameter_options
from .parameter_codec import (
    ParameterCodecError,
    is_editable_parameter,
    parameter_native_scale,
    parameter_native_to_raw,
    parameter_raw_to_native,
)

_MINIMUM = 11
_MAXIMUM = 12
_INCREMENT = 13
_UNIT_KEY = 15

_UNIT_MAP = {
    "unit_amp": "A",
    "unit_ampere": "A",
    "unit_degree": "°",
    "unit_hz": "Hz",
    "unit_ms": "ms",
    "unit_percent": "%",
    "unit_sec": "s",
    "unit_second": "s",
    "unit_seconds": "s",
    "unit_v": "V",
    "unit_volt": "V",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    schema = hub.model_parameter_schema
    if not hub.supports_parameters or schema is None:
        return

    entities = []
    for index, spec in enumerate(schema):
        if not is_editable_parameter(spec):
            continue
        if parameter_options(spec):
            continue
        if spec[_MINIMUM] is None or spec[_MAXIMUM] is None:
            continue
        entities.append(TmtModelParameterNumber(hub, index, spec))
    async_add_entities(entities)


class TmtModelParameterNumber(TmtChowEntity, NumberEntity):
    """Numeric parameter generated from the vendor model schema."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TmtChowHub, index: int, spec: tuple) -> None:
        super().__init__(hub)
        self._index = index
        self._spec = spec
        scale = parameter_native_scale(spec)
        minimum = float(spec[_MINIMUM])
        maximum = float(spec[_MAXIMUM])
        increment = spec[_INCREMENT]
        self._attr_unique_id = f"{hub.uuid}_parameter_{index + 1}"
        self._attr_name = parameter_name(spec)
        self._attr_native_min_value = minimum * scale
        self._attr_native_max_value = maximum * scale
        self._attr_native_step = (
            float(increment) * scale if increment not in (None, 0) else scale
        )
        unit_key = spec[_UNIT_KEY]
        if unit_key:
            self._attr_native_unit_of_measurement = _UNIT_MAP.get(str(unit_key))

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and self.hub.supports_parameters
            and self.hub.parameters is not None
        )

    @property
    def native_value(self) -> float | None:
        values = self.hub.parameters
        if values is None or self._index >= len(values):
            return None
        return parameter_raw_to_native(self._spec, values[self._index])

    async def async_set_native_value(self, value: float) -> None:
        try:
            raw = parameter_native_to_raw(self._spec, value)
        except ParameterCodecError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_parameter_value",
            ) from err
        try:
            await self.hub.async_set_parameter(self._index, raw)
        except TmtCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
