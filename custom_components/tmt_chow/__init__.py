"""TMT Chow custom integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from .const import (
    CONF_CERTIFICATE_PEM,
    CONF_DEVICE_TYPE,
    CONF_ENDPOINT,
    CONF_OURANOS_PIN,
    CONF_PRIVATE_KEY,
    CONF_PRODUCT_TYPE,
    CONF_SOURCE_TAG,
    CONF_THING_NAME,
    CONF_UUID,
    DEFAULT_SOURCE_TAG,
    DOMAIN,
    OURANOS_POLLERS_DATA_KEY,
    PLATFORMS,
)
from .hub import TmtCommandError
from .mqtt import MqttError
from .ouranos_ha_probe import async_probe_ouranos_on_ha
from .ouranos_status import OuranosStatusPoller
from .pedestrian import PEDESTRIAN_STRATEGY_NONE, pedestrian_strategy_for
from .ps21050d_hub import TmtChowHub

_FRONTEND_DATA_KEY = f"{DOMAIN}_frontend_registered"
_FRONTEND_URL_BASE = "/tmt_chow_frontend"
_FRONTEND_MODULE_URL = (
    f"{_FRONTEND_URL_BASE}/pedestrian-more-info.js?v=1.0.4-beta.2"
)
SERVICE_PEDESTRIAN_OPEN = "pedestrian_open"
SERVICE_OURANOS_PROBE = "ouranos_probe"

_LOGGER = logging.getLogger(__name__)


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    """Register the optional TMT Chow cover more-info frontend enhancement."""
    if hass.data.get(_FRONTEND_DATA_KEY):
        return

    # A normal Home Assistant UI installation has both HTTP and frontend loaded.
    # Keep the backend integration usable in headless/test environments too.
    if not hasattr(hass, "http") or DATA_EXTRA_MODULE_URL not in hass.data:
        return

    frontend_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                _FRONTEND_URL_BASE,
                str(frontend_path),
                cache_headers=False,
            )
        ]
    )
    add_extra_js_url(hass, _FRONTEND_MODULE_URL)
    hass.data[_FRONTEND_DATA_KEY] = True


def _find_hub(hass: HomeAssistant, uuid: str) -> TmtChowHub | None:
    """Return one configured TMT Chow hub by UUID."""
    return next(
        (
            candidate
            for candidate in hass.data.get(DOMAIN, {}).values()
            if isinstance(candidate, TmtChowHub) and candidate.uuid == uuid
        ),
        None,
    )


def _is_known_ouranos_candidate(hub: TmtChowHub) -> bool:
    """Return whether this hub matches the confirmed PS19001 OURANOS case.

    A 20-character identifier alone does not identify OURANOS: working WBT
    controllers can use the same identifier length. Until uuid_type is persisted
    in config entries, restrict this native diagnostic to the PS19001 hardware
    confirmed by issue #14.
    """
    return hub.configured_controller_type == "PS19001" and len(hub.uuid) == 20


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services used by controls and diagnostics."""
    if not hass.services.has_service(DOMAIN, SERVICE_PEDESTRIAN_OPEN):

        async def _async_pedestrian_open(call: ServiceCall) -> None:
            uuid = str(call.data.get("uuid", "")).strip()
            if not uuid:
                raise HomeAssistantError("Missing TMT Chow gate UUID")

            hub = _find_hub(hass, uuid)
            if hub is None:
                raise HomeAssistantError("TMT Chow gate not found")
            if (
                pedestrian_strategy_for(hub.controller_type, hub.controller_capabilities)
                == PEDESTRIAN_STRATEGY_NONE
            ):
                raise HomeAssistantError(
                    "Pedestrian opening is not safely supported by this controller"
                )

            try:
                await hub.async_pedestrian_open()
            except TmtCommandError as err:
                raise HomeAssistantError(str(err)) from err

        hass.services.async_register(
            DOMAIN, SERVICE_PEDESTRIAN_OPEN, _async_pedestrian_open
        )
    if not hass.services.has_service(DOMAIN, SERVICE_OURANOS_PROBE):

        async def _async_ouranos_probe(call: ServiceCall) -> dict:
            pin_code = str(call.data.get("pin_code", "")).strip()
            if len(pin_code) != 6 or any(
                char < "0" or char > "9" for char in pin_code
            ):
                raise HomeAssistantError("Gate PIN must contain exactly 6 digits")
            requested_uuid = str(call.data.get("uuid", "")).strip()
            if requested_uuid:
                hub = _find_hub(hass, requested_uuid)
                if hub is None:
                    raise HomeAssistantError("TMT Chow gate not found")
                if not _is_known_ouranos_candidate(hub):
                    raise HomeAssistantError(
                        "Selected gate is not a confirmed PS19001 OURANOS candidate"
                    )
            else:
                candidates = [
                    candidate
                    for candidate in hass.data.get(DOMAIN, {}).values()
                    if isinstance(candidate, TmtChowHub)
                    and _is_known_ouranos_candidate(candidate)
                ]
                if len(candidates) != 1:
                    raise HomeAssistantError(
                        "Specify uuid unless exactly one confirmed PS19001 OURANOS candidate is configured"
                    )
                hub = candidates[0]

            return await async_probe_ouranos_on_ha(hass, hub.uuid, pin_code)

        hass.services.async_register(
            DOMAIN,
            SERVICE_OURANOS_PROBE,
            _async_ouranos_probe,
            supports_response=SupportsResponse.ONLY,
        )


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload an entry after its native status option changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = TmtChowHub(
        uuid=entry.data[CONF_UUID],
        thing_name=entry.data[CONF_THING_NAME],
        name=entry.data.get(CONF_NAME, entry.title),
        endpoint=entry.data[CONF_ENDPOINT],
        certificate_pem=entry.data[CONF_CERTIFICATE_PEM],
        private_key=entry.data[CONF_PRIVATE_KEY],
        source_tag=entry.data.get(CONF_SOURCE_TAG, DEFAULT_SOURCE_TAG),
        product_type=entry.data.get(CONF_PRODUCT_TYPE, ""),
        device_type=entry.data.get(CONF_DEVICE_TYPE, ""),
    )
    poller = None
    pin_code = str(entry.options.get(CONF_OURANOS_PIN, "")).strip()
    if pin_code:
        if (
            _is_known_ouranos_candidate(hub)
            and len(pin_code) == 6
            and all("0" <= char <= "9" for char in pin_code)
        ):
            # Attach before hub startup so the first parameter bootstrap already
            # uses the proven OURANOS route instead of the unavailable WBT path.
            poller = OuranosStatusPoller(hass, hub, pin_code)
        else:
            _LOGGER.warning(
                "Ignoring invalid native PS19001 configuration for %s",
                entry.title,
            )
    try:
        await hub.async_start()
    except MqttError as err:
        if poller is not None:
            await poller.async_stop()
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _register_services(hass)
    await _async_setup_frontend(hass)

    if poller is not None:
        hass.data.setdefault(OURANOS_POLLERS_DATA_KEY, {})[entry.entry_id] = poller
        await poller.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    poller = hass.data.get(OURANOS_POLLERS_DATA_KEY, {}).pop(entry.entry_id, None)
    if poller is not None:
        await poller.async_stop()
    hub: TmtChowHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    return True
