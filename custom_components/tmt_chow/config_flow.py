"""Config flow for TMT Chow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TmtApiError, TmtAuthError, TmtChowApi, TmtDevice
from .const import (
    AUTH_MODE_KAITRON,
    AUTH_MODE_TMT,
    CONF_AUTH_MODE,
    CONF_CERTIFICATE_ARN,
    CONF_CERTIFICATE_PEM,
    CONF_DEVICE_TYPE,
    CONF_ENDPOINT,
    CONF_PRIVATE_KEY,
    CONF_PRODUCT_TYPE,
    CONF_ROLE,
    CONF_SOURCE_TAG,
    CONF_THING_NAME,
    CONF_UUID,
    DEFAULT_SOURCE_TAG,
    DOMAIN,
)


class TmtChowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a gate from the TMT cloud account."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: TmtChowApi | None = None
        self._devices: dict[str, TmtDevice] = {}
        self._auth_mode: str = AUTH_MODE_TMT

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api = TmtChowApi(async_get_clientsession(self.hass))
            self._auth_mode = user_input[CONF_AUTH_MODE]
            try:
                await self._api.async_login(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_AUTH_MODE],
                )
                devices = await self._api.async_get_devices()
            except TmtAuthError:
                errors["base"] = "invalid_auth"
            except TmtApiError:
                errors["base"] = "cannot_connect"
            else:
                self._devices = {device.uuid: device for device in devices}
                if not self._devices:
                    errors["base"] = "no_devices"
                elif len(self._devices) == 1:
                    return await self._async_finish(next(iter(self._devices.values())))
                else:
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_MODE, default=AUTH_MODE_TMT): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=AUTH_MODE_TMT, label="TMT Chow!"
                                ),
                                selector.SelectOptionDict(
                                    value=AUTH_MODE_KAITRON,
                                    label="GatePRO Smart / Kaitron",
                                ),
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device = self._devices.get(user_input[CONF_DEVICE])
            if device is None:
                errors["base"] = "unknown_device"
            else:
                return await self._async_finish(device)

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): vol.In(
                        {
                            uuid: f"{device.name} ({uuid})"
                            for uuid, device in self._devices.items()
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def _async_finish(self, device: TmtDevice) -> ConfigFlowResult:
        await self.async_set_unique_id(device.uuid)
        self._abort_if_unique_id_configured()
        if self._api is None:
            return self.async_abort(reason="cannot_connect")
        try:
            credentials = await self._api.async_bootstrap_aws(device)
        except TmtAuthError:
            return self.async_abort(reason="invalid_auth")
        except TmtApiError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(
            title=device.name,
            data={
                CONF_NAME: device.name,
                CONF_AUTH_MODE: self._auth_mode,
                CONF_UUID: device.uuid,
                CONF_ENDPOINT: credentials.endpoint,
                CONF_THING_NAME: credentials.thing_name,
                CONF_CERTIFICATE_PEM: credentials.certificate_pem,
                CONF_PRIVATE_KEY: credentials.private_key,
                CONF_CERTIFICATE_ARN: credentials.certificate_arn,
                CONF_DEVICE_TYPE: device.device_type,
                CONF_PRODUCT_TYPE: device.product_type,
                CONF_ROLE: device.role,
                CONF_SOURCE_TAG: DEFAULT_SOURCE_TAG,
            },
        )
