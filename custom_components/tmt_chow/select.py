"""Model-specific TMT Chow parameter selectors."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .model_parameter_schemas import parameter_options
from .parameter_codec import is_editable_parameter
from .parameters import PARAMETERS
from .ps21050d_parameters import (
    CONTROLLER_TYPE as PS21050D,
    parameter_options_for as ps21050d_parameter_options,
)
from .ps22027_parameters import (
    CONTROLLER_TYPE as PS22027,
    parameter_options_for as ps22027_parameter_options,
)
from .select_base import (
    TmtModelParameterSelect,
    TmtPS21050DParameterSelect,
    TmtPS22027ParameterSelect,
    TmtParameterSelect,
)

_LEGACY_PS21053 = {"PS21053", "PS21053C"}
_PS25007_APP_MODEL = "PS25007"
_PS25007A_PARAMETER_MODEL = "PS25007A"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]
    schema = hub.model_parameter_schema
    ps25007a_profile = (
        hub.configured_controller_type == _PS25007_APP_MODEL
        and hub.parameter_model_type == _PS25007A_PARAMETER_MODEL
    )
    legacy_17_value_profile = hub.controller_type in _LEGACY_PS21053 or ps25007a_profile
    if schema is None or (not hub.supports_parameters and not legacy_17_value_profile):
        return

    # PS21053/PS21053C and the exact PS25007 -> PS25007A AutoProduct alias
    # share the same 17 wire positions and option semantics.  During the short
    # configured-only PS25007 startup phase the entities may exist unavailable;
    # writes become possible only after live DEV INFO confirms PS25007A.
    if legacy_17_value_profile:
        async_add_entities(
            TmtParameterSelect(hub, index, definition)
            for index, definition in enumerate(PARAMETERS)
        )
        return

    if hub.parameter_model_type == PS21050D:
        async_add_entities(
            TmtPS21050DParameterSelect(hub, index, spec)
            for index, spec in enumerate(schema)
            if is_editable_parameter(spec) and ps21050d_parameter_options(index)
        )
        return

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
