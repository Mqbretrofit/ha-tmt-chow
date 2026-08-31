"""TMT Chow REST API used during config flow setup."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientSession

from .const import (
    AUTH_MODE_KAITRON,
    AUTH_MODE_TMT,
    BASE_URL,
    CERTIFICATE_PATH,
    DEVICES_PATH,
    KAITRON_BASE_URL,
    KAITRON_LOGIN_PATH,
    LOGIN_PATH,
    OAUTH_CLIENT,
    POLICY_PATH,
)


_LOGGER = logging.getLogger(__name__)


class TmtApiError(Exception):
    """Base TMT API error."""


class TmtAuthError(TmtApiError):
    """Raised when the supplied account is rejected."""


@dataclass(slots=True, frozen=True)
class TmtDevice:
    """A device returned by the TMT account API."""

    name: str
    uuid: str
    role: str
    device_type: str
    product_type: str
    iot_endpoint: str


@dataclass(slots=True, frozen=True)
class TmtAwsCredentials:
    """Dedicated AWS IoT certificate material."""

    private_key: str
    certificate_pem: str
    certificate_arn: str
    endpoint: str
    thing_name: str


def _value(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data and data[name] not in (None, ""):
            return data[name]
    nested = data.get("data")
    if isinstance(nested, dict):
        for name in names:
            if name in nested and nested[name] not in (None, ""):
                return nested[name]
    return None


class TmtChowApi:
    """Small async REST client for account setup and AWS bootstrap."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._access_token: str | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        basic_auth: bool = False,
        base_url: str = BASE_URL,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-TMT-Chow/0.1.0-beta.1",
        }
        if basic_auth:
            encoded = base64.b64encode(OAUTH_CLIENT.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            async with self._session.request(
                method,
                urljoin(base_url, path),
                headers=headers,
                json=json,
                timeout=30,
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, TypeError):
                    payload = {}

                if response.status in (400, 401, 403):
                    raise TmtAuthError(f"TMT API rejected the request: {response.status}")
                if response.status < 200 or response.status >= 300:
                    raise TmtApiError(f"TMT API HTTP {response.status}")
                if not isinstance(payload, dict):
                    raise TmtApiError("Unexpected TMT API response")
                return payload
        except TmtApiError:
            raise
        except (ClientError, TimeoutError) as err:
            raise TmtApiError("Cannot connect to the TMT API") from err

    async def async_login(
        self,
        username: str,
        password: str,
        auth_mode: str = AUTH_MODE_TMT,
    ) -> None:
        """Authenticate using the selected official app backend.

        TMT Chow uses the installer.tmt-automation.com OAuth endpoint.
        GatePRO Smart authenticates directly against the Kaitron token endpoint,
        then uses the returned bearer token with the normal TMT user/device APIs.
        """
        login_payload = {
            "username": username,
            "password": password,
            "grant_type": "password",
            "scope": "user",
            "app_type_index": 1,
        }

        if auth_mode == AUTH_MODE_TMT:
            payload = await self._request(
                "POST",
                LOGIN_PATH,
                json=login_payload,
                basic_auth=True,
            )
            backend = "tmt_chow"
        elif auth_mode == AUTH_MODE_KAITRON:
            payload = await self._request(
                "POST",
                KAITRON_LOGIN_PATH,
                json=login_payload,
                basic_auth=True,
                base_url=KAITRON_BASE_URL,
            )
            backend = "gatepro_kaitron"
        else:
            raise TmtApiError(f"Unsupported authentication mode: {auth_mode}")

        token = _value(payload, "access_token", "token")
        if not isinstance(token, str) or not token:
            raise TmtAuthError(
                f"The {backend} login response did not contain an access token"
            )

        self._access_token = token
        _LOGGER.debug("TMT Chow authenticated via %s backend", backend)

    async def async_get_devices(self) -> list[TmtDevice]:
        payload = await self._request("GET", DEVICES_PATH)
        friendly_names: dict[str, str] = {}
        for custom in payload.get("custom_info", []) or []:
            if isinstance(custom, dict) and custom.get("uuid"):
                friendly_names[str(custom["uuid"])] = str(
                    custom.get("display_name") or "TMT gate"
                )

        devices: list[TmtDevice] = []
        for bucket, role in (
            ("admin_devices", "admin"),
            ("user_devices", "user"),
            ("share_devices", "shared"),
        ):
            for raw in payload.get(bucket, []) or []:
                if not isinstance(raw, dict) or not raw.get("uuid"):
                    continue
                uuid = str(raw["uuid"])
                device_type = str(raw.get("devies_type") or raw.get("device_type") or "")
                endpoint = str(raw.get("iot_endpoint") or "")
                if not endpoint:
                    continue
                devices.append(
                    TmtDevice(
                        name=friendly_names.get(uuid, str(raw.get("name") or "TMT gate")),
                        uuid=uuid,
                        role=role,
                        device_type=device_type,
                        product_type=str(raw.get("product_type") or ""),
                        iot_endpoint=endpoint,
                    )
                )
        return devices

    async def async_bootstrap_aws(self, device: TmtDevice) -> TmtAwsCredentials:
        """Create one dedicated certificate and attach its device policy."""
        certificate = await self._request(
            "PUT", CERTIFICATE_PATH, json={"app": 0}
        )
        private_key = _value(certificate, "PrivateKey", "privateKey", "private_key")
        certificate_pem = _value(
            certificate, "certificatePem", "CertificatePem", "certificate_pem"
        )
        certificate_arn = _value(
            certificate,
            "user_certificateArn",
            "certificateArn",
            "certificate_arn",
        )
        endpoint = _value(certificate, "endpoint", "iot_endpoint") or device.iot_endpoint

        if not all(
            isinstance(item, str) and item
            for item in (private_key, certificate_pem, certificate_arn, endpoint)
        ):
            raise TmtApiError("AWS certificate response is incomplete")

        policy = await self._request(
            "PUT",
            POLICY_PATH,
            json={
                "user_certificateArn": certificate_arn,
                "endpoint": endpoint,
                "uuid": device.uuid,
            },
        )
        thing_name = _value(policy, "thing_name", "thingName", "ThingName")
        if not isinstance(thing_name, str) or not thing_name:
            thing_name = device.uuid

        return TmtAwsCredentials(
            private_key=private_key,
            certificate_pem=certificate_pem,
            certificate_arn=certificate_arn,
            endpoint=endpoint,
            thing_name=thing_name,
        )
