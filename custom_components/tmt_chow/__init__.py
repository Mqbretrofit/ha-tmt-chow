"""TMT Chow custom integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

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
from .hub import TmtChowHub
from .mqtt import MqttError


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hub: TmtChowHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    return True
