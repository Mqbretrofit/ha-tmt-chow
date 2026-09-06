"""TMT Chow custom integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from .const import (
    CONF_CERTIFICATE_PEM,
    CONF_DEVICE_TYPE,
    CONF_ENDPOINT,
    CONF_PRIVATE_KEY,
    CONF_PRODUCT_TYPE,
    CONF_SOURCE_TAG,
    CONF_THING_NAME,
    CONF_UUID,
    DEFAULT_SOURCE_TAG,
    DOMAIN,
    PLATFORMS,
)
from .controller_types import CAPABILITY_PEDESTRIAN
from .hub import TmtCommandError
from .mqtt import MqttError
from .ps21050d_hub import TmtChowHub

_FRONTEND_DATA_KEY = f"{DOMAIN}_frontend_registered"
_FRONTEND_URL_BASE = "/tmt_chow_frontend"
_FRONTEND_MODULE_URL = (
    f"{_FRONTEND_URL_BASE}/pedestrian-more-info.js?v=1.0.4-beta.1"
)
SERVICE_PEDESTRIAN_OPEN = "pedestrian_open"


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


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services used by the frontend control."""
    if hass.services.has_service(DOMAIN, SERVICE_PEDESTRIAN_OPEN):
        return

    async def _async_pedestrian_open(call: ServiceCall) -> None:
        uuid = str(call.data.get("uuid", "")).strip()
        if not uuid:
            raise HomeAssistantError("Missing TMT Chow gate UUID")

        hub = next(
            (
                candidate
                for candidate in hass.data.get(DOMAIN, {}).values()
                if isinstance(candidate, TmtChowHub) and candidate.uuid == uuid
            ),
            None,
        )
        if hub is None:
            raise HomeAssistantError("TMT Chow gate not found")
        if CAPABILITY_PEDESTRIAN not in hub.controller_capabilities:
            raise HomeAssistantError(
                "Pedestrian opening is not supported by this controller"
            )

        try:
            await hub.async_pedestrian_open()
        except TmtCommandError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_PEDESTRIAN_OPEN, _async_pedestrian_open)


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
    try:
        await hub.async_start()
    except MqttError as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    _register_services(hass)
    await _async_setup_frontend(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hub: TmtChowHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    return True
