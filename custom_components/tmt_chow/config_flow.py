"""Config flow for TMT Chow."""

from __future__ import annotations

import hashlib
import logging
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


_LOGGER = logging.getLogger(__name__)


def _fingerprint(value: str | None) -> str:
    if not value:
        return "none"
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


class TmtChowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a gate from the TMT cloud account."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: TmtChowApi | None = None
        self._devices: dict[str, TmtDevice] = {}
        self._auth_mode: str = AUTH_MODE_TMT
        self._pending_activation_account: str | None = None
        self._pending_activation_email: str | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api = TmtChowApi(async_get_clientsession(self.hass))
            self._auth_mode = user_input[CONF_AUTH_MODE]
            username = str(user_input[CONF_USERNAME])
            password = str(user_input[CONF_PASSWORD])
            _LOGGER.warning(
                "TMTDIAG CONFIG_FLOW_LOGIN_SUBMIT auth_mode=%s username_len=%s "
                "username_sha256=%s password_len=%s",
                self._auth_mode,
                len(username),
                _fingerprint(username),
                len(password),
            )
            try:
                await self._api.async_login(
                    username,
                    password,
                    user_input[CONF_AUTH_MODE],
                )
                devices = await self._api.async_get_devices()
            except TmtAuthError as err:
                error_payload = err.payload or {}
                error_code = str(error_payload.get("error_code", ""))
                returned_email = error_payload.get("email")
                _LOGGER.warning(
                    "TMTDIAG CONFIG_FLOW_AUTH_ERROR auth_mode=%s "
                    "username_sha256=%s error_code=%s "
                    "activation_email_available=%s error=%s",
                    self._auth_mode,
                    _fingerprint(username),
                    error_code or "none",
                    isinstance(returned_email, str) and bool(returned_email),
                    err,
                )
                if (
                    self._auth_mode == AUTH_MODE_TMT
                    and error_code == "-1003"
                ):
                    self._pending_activation_account = username
                    self._pending_activation_email = (
                        returned_email
                        if isinstance(returned_email, str)
                        else None
                    )
                    return await self.async_step_activation()
                errors["base"] = "invalid_auth"
            except TmtApiError as err:
                _LOGGER.warning(
                    "TMTDIAG CONFIG_FLOW_API_ERROR auth_mode=%s "
                    "username_sha256=%s error_type=%s error=%s",
                    self._auth_mode,
                    _fingerprint(username),
                    type(err).__name__,
                    err,
                )
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception(
                    "TMTDIAG CONFIG_FLOW_UNEXPECTED_ERROR auth_mode=%s "
                    "username_sha256=%s error_type=%s",
                    self._auth_mode,
                    _fingerprint(username),
                    type(err).__name__,
                )
                errors["base"] = "cannot_connect"
            else:
                self._devices = {device.uuid: device for device in devices}
                _LOGGER.warning(
                    "TMTDIAG CONFIG_FLOW_LOGIN_AND_DEVICE_QUERY_OK auth_mode=%s "
                    "device_count=%s",
                    self._auth_mode,
                    len(self._devices),
                )
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

    async def async_step_activation(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Offer the official TMT activation-email flow after error -1003."""
        errors: dict[str, str] = {}
        account = self._pending_activation_account
        if account is None or self._api is None:
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            email = str(user_input["email"]).strip()
            _LOGGER.warning(
                "TMTDIAG CONFIG_FLOW_ACTIVATION_SUBMIT account_sha256=%s "
                "email_len=%s email_sha256=%s",
                _fingerprint(account),
                len(email),
                _fingerprint(email),
            )
            try:
                await self._api.async_send_activation_email(account, email)
            except TmtAuthError as err:
                _LOGGER.warning(
                    "TMTDIAG CONFIG_FLOW_ACTIVATION_AUTH_ERROR "
                    "account_sha256=%s email_sha256=%s error=%s",
                    _fingerprint(account),
                    _fingerprint(email),
                    err,
                )
                errors["base"] = "activation_failed"
            except TmtApiError as err:
                _LOGGER.warning(
                    "TMTDIAG CONFIG_FLOW_ACTIVATION_API_ERROR "
                    "account_sha256=%s email_sha256=%s error=%s",
                    _fingerprint(account),
                    _fingerprint(email),
                    err,
                )
                errors["base"] = "cannot_connect"
            else:
                return self.async_abort(reason="activation_email_sent")

        schema_key = vol.Required
        if self._pending_activation_email:
            email_field = schema_key(
                "email",
                default=self._pending_activation_email,
            )
        else:
            email_field = schema_key("email")

        return self.async_show_form(
            step_id="activation",
            data_schema=vol.Schema({email_field: str}),
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
        _LOGGER.warning(
            "TMTDIAG CONFIG_FLOW_FINISH_START auth_mode=%s device_role=%s "
            "device_type=%s product_type=%s",
            self._auth_mode,
            device.role,
            device.device_type,
            device.product_type,
        )
        try:
            credentials = await self._api.async_bootstrap_aws(device)
        except TmtAuthError as err:
            _LOGGER.warning("TMTDIAG CONFIG_FLOW_BOOTSTRAP_AUTH_ERROR error=%s", err)
            return self.async_abort(reason="invalid_auth")
        except TmtApiError as err:
            _LOGGER.warning(
                "TMTDIAG CONFIG_FLOW_BOOTSTRAP_API_ERROR error_type=%s error=%s",
                type(err).__name__,
                err,
            )
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
