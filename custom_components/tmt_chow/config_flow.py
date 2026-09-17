"""Config flow for TMT Chow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_DEVICE, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TmtApiError, TmtAuthError, TmtChowApi, TmtDevice
from .const import (
    CONF_CERTIFICATE_ARN,
    CONF_CERTIFICATE_PEM,
    CONF_DEVICE_TYPE,
    CONF_ENDPOINT,
    CONF_OURANOS_PIN,
    CONF_PRIVATE_KEY,
    CONF_PRODUCT_TYPE,
    CONF_PROPOSAL,
    CONF_PROPOSAL_FETCH_STATUS,
    CONF_PROPOSAL_ID,
    CONF_ROLE,
    CONF_SOURCE_TAG,
    CONF_THING_NAME,
    CONF_UUID,
    DEFAULT_SOURCE_TAG,
    DOMAIN,
)
from .proposal import proposal_id_for


class TmtChowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a gate from the TMT cloud account."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: TmtChowApi | None = None
        self._devices: dict[str, TmtDevice] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the TMT Chow options flow."""
        return TmtChowOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api = TmtChowApi(async_get_clientsession(self.hass))
            try:
                await self._api.async_login(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
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

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Refresh cloud metadata/AutoProduct Proposal for an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            api = TmtChowApi(async_get_clientsession(self.hass))
            try:
                await api.async_login(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                devices = await api.async_get_devices()
            except TmtAuthError:
                errors["base"] = "invalid_auth"
            except TmtApiError:
                errors["base"] = "cannot_connect"
            else:
                uuid = str(entry.data.get(CONF_UUID) or "")
                device = next((item for item in devices if item.uuid == uuid), None)
                if device is None:
                    errors["base"] = "unknown_device"
                else:
                    controller_type = device.device_type or str(
                        entry.data.get(CONF_DEVICE_TYPE) or ""
                    )
                    proposal_id = proposal_id_for(controller_type)
                    proposal: dict[str, Any] | None = None
                    proposal_status = (
                        "not_applicable" if proposal_id is None else "not_found"
                    )
                    if proposal_id is not None:
                        try:
                            proposal = await api.async_get_proposal(controller_type)
                        except TmtAuthError:
                            errors["base"] = "invalid_auth"
                        except TmtApiError:
                            errors["base"] = "cannot_connect"
                        else:
                            if proposal is not None:
                                proposal_status = "available"

                    if not errors:
                        await self.async_set_unique_id(device.uuid)
                        self._abort_if_unique_id_mismatch()

                        data = dict(entry.data)
                        data[CONF_DEVICE_TYPE] = controller_type
                        data[CONF_PRODUCT_TYPE] = device.product_type
                        data[CONF_ROLE] = device.role
                        data[CONF_PROPOSAL_FETCH_STATUS] = proposal_status
                        data.pop(CONF_PROPOSAL_ID, None)
                        data.pop(CONF_PROPOSAL, None)
                        if proposal_id is not None:
                            data[CONF_PROPOSAL_ID] = proposal_id
                        if proposal is not None:
                            data[CONF_PROPOSAL] = proposal

                        # The integration already has an update listener that
                        # reloads the entry.  Update directly and abort instead
                        # of calling async_update_reload_and_abort, which would
                        # cause a double reload on Home Assistant 2026.6+.
                        self.hass.config_entries.async_update_entry(entry, data=data)
                        return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _async_finish(self, device: TmtDevice) -> ConfigFlowResult:
        await self.async_set_unique_id(device.uuid)
        self._abort_if_unique_id_configured()
        if self._api is None:
            return self.async_abort(reason="cannot_connect")

        # TMT Chow 3.2.0 resolves controllers missing from its static catalog via
        # ResponseProposalInfo/AutoProduct.  Capture that vendor profile while the
        # config flow still owns a short-lived Bearer token.  Proposal discovery
        # is optional and must never break a controller that already works through
        # the verified static integration paths.
        proposal_id = proposal_id_for(device.device_type)
        proposal: dict[str, Any] | None = None
        proposal_status = "not_applicable" if proposal_id is None else "not_found"
        if proposal_id is not None:
            try:
                proposal = await self._api.async_get_proposal(device.device_type)
            except TmtApiError:
                proposal_status = "error"
            else:
                if proposal is not None:
                    proposal_status = "available"

        try:
            credentials = await self._api.async_bootstrap_aws(device)
        except TmtAuthError:
            return self.async_abort(reason="invalid_auth")
        except TmtApiError:
            return self.async_abort(reason="cannot_connect")

        data: dict[str, Any] = {
            CONF_NAME: device.name,
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
            CONF_PROPOSAL_FETCH_STATUS: proposal_status,
        }
        if proposal_id is not None:
            data[CONF_PROPOSAL_ID] = proposal_id
        if proposal is not None:
            data[CONF_PROPOSAL] = proposal

        return self.async_create_entry(title=device.name, data=data)


class TmtChowOptionsFlow(OptionsFlow):
    """Configure the opt-in native PS19001 status reader."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure native status polling for confirmed PS19001 hardware."""
        if (
            self.config_entry.data.get(CONF_DEVICE_TYPE) != "PS19001"
            or len(str(self.config_entry.data.get(CONF_UUID, ""))) != 20
        ):
            return self.async_abort(reason="not_ouranos_candidate")

        errors: dict[str, str] = {}
        if user_input is not None:
            pin_code = str(user_input.get(CONF_OURANOS_PIN, "")).strip()
            if pin_code and (
                len(pin_code) != 6
                or any(char < "0" or char > "9" for char in pin_code)
            ):
                errors[CONF_OURANOS_PIN] = "invalid_pin"
            else:
                return self.async_create_entry(
                    title="", data={CONF_OURANOS_PIN: pin_code}
                )

        current_pin = str(self.config_entry.options.get(CONF_OURANOS_PIN, ""))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_OURANOS_PIN, default=current_pin): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )
