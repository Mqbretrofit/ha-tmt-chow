"""TMT Chow REST API used during config flow setup."""

from __future__ import annotations

import base64
import hashlib
import json as jsonlib
import logging
import re
import time
import uuid
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
    FIREBASE_IDENTITY_BASE_URL,
    FIREBASE_SIGN_IN_PATH,
    FIREBASE_VERIFY_PATH,
    GATEPRO_APP_TYPE_INDEX,
    KAITRON_BASE_URL,
    KAITRON_LOGIN_PATH,
    LOGIN_PATH,
    OAUTH_CLIENT,
    POLICY_PATH,
    TMT_APP_TYPE_INDEX,
    TMT_FIREBASE_LANGUAGE,
)


_LOGGER = logging.getLogger(__name__)

_SECRET_KEY_MARKERS = (
    "authorization",
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "privatekey",
    "certificatepem",
    "certificatearn",
    "cookie",
)
_PERSONAL_KEYS = {
    "username",
    "user",
    "nickname",
    "email",
    "account",
    "accountid",
    "userid",
}
_SAFE_RESPONSE_HEADERS = (
    "content-type",
    "content-length",
    "date",
    "server",
    "via",
    "x-request-id",
    "x-correlation-id",
    "cf-ray",
    "cf-cache-status",
)


class TmtApiError(Exception):
    """Base TMT API error."""


class TmtAuthError(TmtApiError):
    """Raised when the supplied account is rejected."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


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


def _fingerprint(value: str | None) -> str:
    """Return a non-reversible short fingerprint for correlation."""
    if not value:
        return "none"
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _normalized_key(key: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def _scrub_string(value: str, sensitive_values: tuple[str, ...] = ()) -> str:
    """Remove submitted credentials and common inline credential formats."""
    scrubbed = value
    for sensitive in sensitive_values:
        if sensitive:
            scrubbed = scrubbed.replace(sensitive, "<redacted-submitted-value>")
    scrubbed = re.sub(
        r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+",
        "<redacted-authorization>",
        scrubbed,
    )
    scrubbed = re.sub(
        r"(?i)(access[_-]?token|refresh[_-]?token|id[_-]?token|password|"
        r"client[_-]?secret)\s*[:=]\s*[\"']?[^\s,}\"']+",
        r"\1=<redacted>",
        scrubbed,
    )
    scrubbed = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "<redacted-email>",
        scrubbed,
    )
    if len(scrubbed) > 4000:
        return scrubbed[:4000] + f"... <truncated {len(scrubbed) - 4000} chars>"
    return scrubbed


def _redact(
    value: Any,
    key: str | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> Any:
    """Recursively redact secrets and personal identifiers."""
    normalized = _normalized_key(key)
    if any(marker in normalized for marker in _SECRET_KEY_MARKERS):
        if isinstance(value, str):
            return f"<redacted len={len(value)}>"
        return "<redacted>"
    if normalized in _PERSONAL_KEYS:
        if isinstance(value, str):
            return f"<redacted personal len={len(value)} sha256={_fingerprint(value)}>"
        return "<redacted personal>"
    if isinstance(value, dict):
        return {
            str(k): _redact(v, str(k), sensitive_values)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v, sensitive_values=sensitive_values) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact(v, sensitive_values=sensitive_values) for v in value)
    if isinstance(value, str):
        return _scrub_string(value, sensitive_values)
    return value


def _safe_request_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a useful but credential-safe representation of a request body."""
    if payload is None:
        return None
    safe = _redact(payload)
    if isinstance(safe, dict) and isinstance(payload.get("username"), str):
        username = str(payload["username"])
        safe["username"] = (
            f"<redacted username len={len(username)} sha256={_fingerprint(username)}>"
        )
    return safe


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "cookie", "set-cookie"}:
            scheme = value.split(" ", 1)[0] if value else "unknown"
            safe[key] = f"<redacted {scheme}>"
        else:
            safe[key] = value
    return safe


def _response_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = headers.get(key)
        if value is not None:
            result[key] = str(value)
    return result


class TmtChowApi:
    """Small async REST client for account setup and AWS bootstrap."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._access_token: str | None = None
        self._diagnostic_sensitive_values: tuple[str, ...] = ()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        basic_auth: bool = False,
        base_url: str = BASE_URL,
        phase: str = "api",
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex[:10]
        url = urljoin(base_url, path)
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-TMT-Chow/1.0.1-beta.5-firebase-diagnostics.1",
        }
        if basic_auth:
            encoded = base64.b64encode(OAUTH_CLIENT.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        _LOGGER.debug(
            "TMTDIAG request_start id=%s phase=%s method=%s url=%s "
            "base_url=%s path=%s timeout=30 basic_auth=%s bearer_present=%s "
            "headers=%s payload=%s",
            request_id,
            phase,
            method,
            url,
            base_url,
            path,
            basic_auth,
            bool(self._access_token and not basic_auth),
            _safe_headers(headers),
            _safe_request_payload(json),
        )

        started = time.monotonic()
        response = None
        raw_text = ""
        payload: Any = None
        peer = None
        ssl_info = None
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json,
                timeout=30,
            ) as response:
                elapsed_ms = int((time.monotonic() - started) * 1000)

                try:
                    connection = response.connection
                    transport = connection.transport if connection else None
                    if transport:
                        peer = transport.get_extra_info("peername")
                        ssl_object = transport.get_extra_info("ssl_object")
                        if ssl_object:
                            ssl_info = {
                                "version": ssl_object.version(),
                                "cipher": (
                                    ssl_object.cipher()[0]
                                    if ssl_object.cipher()
                                    else None
                                ),
                            }
                except Exception:  # diagnostics must never break setup
                    peer = None
                    ssl_info = None

                raw_text = await response.text(errors="replace")
                try:
                    payload = jsonlib.loads(raw_text) if raw_text else {}
                except (ValueError, TypeError):
                    payload = None

                history = [
                    {
                        "status": item.status,
                        "url": str(item.url),
                        "location_present": bool(item.headers.get("Location")),
                    }
                    for item in response.history
                ]

                safe_body: Any
                if isinstance(payload, (dict, list)):
                    safe_body = _redact(
                        payload,
                        sensitive_values=self._diagnostic_sensitive_values,
                    )
                else:
                    safe_body = _redact(
                        raw_text,
                        sensitive_values=self._diagnostic_sensitive_values,
                    )

                _LOGGER.debug(
                    "TMTDIAG response id=%s phase=%s status=%s reason=%r "
                    "elapsed_ms=%s final_url=%s redirects=%s peer=%s ssl=%s "
                    "headers=%s body=%s",
                    request_id,
                    phase,
                    response.status,
                    response.reason,
                    elapsed_ms,
                    response.url,
                    history,
                    peer,
                    ssl_info,
                    _response_headers(response.headers),
                    safe_body,
                )

                if response.status in (400, 401, 403):
                    _LOGGER.warning(
                        "TMTDIAG AUTH_FAILURE id=%s phase=%s method=%s url=%s "
                        "status=%s reason=%r elapsed_ms=%s final_url=%s "
                        "redirects=%s peer=%s ssl=%s request_headers=%s "
                        "request_payload=%s response_headers=%s response_body=%s",
                        request_id,
                        phase,
                        method,
                        url,
                        response.status,
                        response.reason,
                        elapsed_ms,
                        response.url,
                        history,
                        peer,
                        ssl_info,
                        _safe_headers(headers),
                        _safe_request_payload(json),
                        _response_headers(response.headers),
                        safe_body,
                    )
                    raise TmtAuthError(
                        f"TMT API rejected the request: {response.status} "
                        f"(diagnostic id {request_id})",
                        status=response.status,
                        payload=payload if isinstance(payload, dict) else None,
                    )

                if response.status < 200 or response.status >= 300:
                    _LOGGER.warning(
                        "TMTDIAG HTTP_FAILURE id=%s phase=%s method=%s url=%s "
                        "status=%s reason=%r elapsed_ms=%s final_url=%s "
                        "redirects=%s peer=%s ssl=%s request_payload=%s "
                        "response_headers=%s response_body=%s",
                        request_id,
                        phase,
                        method,
                        url,
                        response.status,
                        response.reason,
                        elapsed_ms,
                        response.url,
                        history,
                        peer,
                        ssl_info,
                        _safe_request_payload(json),
                        _response_headers(response.headers),
                        safe_body,
                    )
                    raise TmtApiError(
                        f"TMT API HTTP {response.status} "
                        f"(diagnostic id {request_id})"
                    )

                if not isinstance(payload, dict):
                    _LOGGER.warning(
                        "TMTDIAG BAD_RESPONSE id=%s phase=%s status=%s "
                        "content_type=%s body=%s",
                        request_id,
                        phase,
                        response.status,
                        response.headers.get("Content-Type"),
                        safe_body,
                    )
                    raise TmtApiError(
                        f"Unexpected TMT API response (diagnostic id {request_id})"
                    )

                return payload

        except TmtApiError:
            raise
        except (ClientError, TimeoutError) as err:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            _LOGGER.warning(
                "TMTDIAG CONNECTION_FAILURE id=%s phase=%s method=%s url=%s "
                "elapsed_ms=%s exception_type=%s exception=%r",
                request_id,
                phase,
                method,
                url,
                elapsed_ms,
                type(err).__name__,
                err,
            )
            _LOGGER.debug(
                "TMTDIAG connection traceback id=%s phase=%s",
                request_id,
                phase,
                exc_info=True,
            )
            raise TmtApiError(
                f"Cannot connect to the TMT API (diagnostic id {request_id})"
            ) from err
        except Exception as err:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            _LOGGER.exception(
                "TMTDIAG UNEXPECTED_FAILURE id=%s phase=%s method=%s url=%s "
                "elapsed_ms=%s exception_type=%s",
                request_id,
                phase,
                method,
                url,
                elapsed_ms,
                type(err).__name__,
            )
            raise

    async def _async_firebase_login(
        self,
        email: str,
        password: str,
        app_type_index: int,
        *,
        source: str,
    ) -> dict[str, Any]:
        """Authenticate with Firebase, then exchange its ID token with TMT."""
        self._diagnostic_sensitive_values = tuple(
            dict.fromkeys((*self._diagnostic_sensitive_values, email, password))
        )
        email_fp = _fingerprint(email)
        _LOGGER.warning(
            "TMTDIAG FIREBASE_LOGIN_SELECTED source=%s email_len=%s "
            "email_sha256=%s app_type_index=%s",
            source,
            len(email),
            email_fp,
            app_type_index,
        )
        firebase_response = await self._request(
            "POST",
            FIREBASE_SIGN_IN_PATH,
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
            base_url=FIREBASE_IDENTITY_BASE_URL,
            phase="login:tmt_chow_firebase_identity",
        )
        id_token = _value(firebase_response, "idToken")
        if not isinstance(id_token, str) or not id_token:
            raise TmtAuthError(
                "Firebase login response did not contain an ID token"
            )
        _LOGGER.warning(
            "TMTDIAG FIREBASE_IDENTITY_OK source=%s email_sha256=%s "
            "local_id_present=%s id_token_present=True",
            source,
            email_fp,
            bool(_value(firebase_response, "localId")),
        )
        return await self._request(
            "POST",
            FIREBASE_VERIFY_PATH,
            json={
                "id_token": id_token,
                "language": TMT_FIREBASE_LANGUAGE,
                "app_type_index": app_type_index,
            },
            basic_auth=True,
            base_url=BASE_URL,
            phase="login:tmt_chow_firebase_verify",
        )

    async def async_login(
        self,
        username: str,
        password: str,
        auth_mode: str = AUTH_MODE_TMT,
    ) -> None:
        """Authenticate using the selected official app backend."""
        if auth_mode == AUTH_MODE_TMT:
            app_type_index = TMT_APP_TYPE_INDEX
            backend = "tmt_chow"
            base_url = BASE_URL
            path = LOGIN_PATH
        elif auth_mode == AUTH_MODE_KAITRON:
            app_type_index = GATEPRO_APP_TYPE_INDEX
            backend = "gatepro_kaitron"
            base_url = KAITRON_BASE_URL
            path = KAITRON_LOGIN_PATH
        else:
            _LOGGER.warning(
                "TMTDIAG LOGIN_CONFIG_ERROR unsupported_auth_mode=%r", auth_mode
            )
            raise TmtApiError(f"Unsupported authentication mode: {auth_mode}")

        self._diagnostic_sensitive_values = tuple(
            value for value in (username, password) if value
        )
        username_fp = _fingerprint(username)
        _LOGGER.warning(
            "TMTDIAG LOGIN_ATTEMPT backend=%s auth_mode=%s base_url=%s path=%s "
            "app_type_index=%s username_len=%s username_sha256=%s "
            "password_len=%s",
            backend,
            auth_mode,
            base_url,
            path,
            app_type_index,
            len(username),
            username_fp,
            len(password),
        )

        try:
            if auth_mode == AUTH_MODE_TMT and "@" in username:
                backend = "tmt_chow_firebase_email"
                payload = await self._async_firebase_login(
                    username,
                    password,
                    app_type_index,
                    source="email_input",
                )
            else:
                login_payload = {
                    "username": username,
                    "password": password,
                    "grant_type": "password",
                    "scope": "user",
                    "app_type_index": app_type_index,
                }
                try:
                    payload = await self._request(
                        "POST",
                        path,
                        json=login_payload,
                        basic_auth=True,
                        base_url=base_url,
                        phase=f"login:{backend}",
                    )
                except TmtAuthError as err:
                    error_payload = err.payload or {}
                    returned_email = error_payload.get("email")
                    error_code = str(error_payload.get("error_code", ""))
                    if (
                        auth_mode == AUTH_MODE_TMT
                        and error_code == "-1003"
                        and isinstance(returned_email, str)
                        and returned_email
                    ):
                        backend = "tmt_chow_firebase_fallback"
                        _LOGGER.warning(
                            "TMTDIAG FIREBASE_FALLBACK_TRIGGERED "
                            "legacy_error_code=-1003 username_sha256=%s "
                            "returned_email_len=%s returned_email_sha256=%s",
                            username_fp,
                            len(returned_email),
                            _fingerprint(returned_email),
                        )
                        payload = await self._async_firebase_login(
                            returned_email,
                            password,
                            app_type_index,
                            source="legacy_error_1003",
                        )
                    else:
                        raise
        except TmtAuthError:
            _LOGGER.warning(
                "TMTDIAG LOGIN_REJECTED backend=%s auth_mode=%s "
                "app_type_index=%s username_len=%s username_sha256=%s",
                backend,
                auth_mode,
                app_type_index,
                len(username),
                username_fp,
            )
            raise
        except TmtApiError:
            _LOGGER.warning(
                "TMTDIAG LOGIN_TRANSPORT_OR_API_ERROR backend=%s "
                "auth_mode=%s app_type_index=%s username_len=%s "
                "username_sha256=%s",
                backend,
                auth_mode,
                app_type_index,
                len(username),
                username_fp,
            )
            raise

        token = _value(payload, "access_token", "token")
        refresh_token = _value(payload, "refresh_token")
        token_type = _value(payload, "token_type")
        expires_in = _value(payload, "expires_in")

        _LOGGER.warning(
            "TMTDIAG LOGIN_RESPONSE_OK backend=%s auth_mode=%s payload_keys=%s "
            "nested_data_keys=%s access_token_present=%s access_token_len=%s "
            "refresh_token_present=%s refresh_token_len=%s token_type=%r "
            "expires_in=%r",
            backend,
            auth_mode,
            sorted(payload.keys()),
            sorted(payload.get("data", {}).keys())
            if isinstance(payload.get("data"), dict)
            else [],
            isinstance(token, str) and bool(token),
            len(token) if isinstance(token, str) else 0,
            isinstance(refresh_token, str) and bool(refresh_token),
            len(refresh_token) if isinstance(refresh_token, str) else 0,
            token_type,
            expires_in,
        )

        if not isinstance(token, str) or not token:
            raise TmtAuthError(
                f"The {backend} login response did not contain an access token"
            )

        self._access_token = token

    async def async_get_devices(self) -> list[TmtDevice]:
        _LOGGER.warning("TMTDIAG DEVICE_QUERY_START bearer_present=%s", bool(self._access_token))
        payload = await self._request("GET", DEVICES_PATH, phase="devices")
        _LOGGER.warning(
            "TMTDIAG DEVICE_QUERY_RESPONSE top_level_keys=%s admin_count=%s "
            "user_count=%s share_count=%s custom_info_count=%s",
            sorted(payload.keys()),
            len(payload.get("admin_devices", []) or []),
            len(payload.get("user_devices", []) or []),
            len(payload.get("share_devices", []) or []),
            len(payload.get("custom_info", []) or []),
        )

        friendly_names: dict[str, str] = {}
        for custom in payload.get("custom_info", []) or []:
            if isinstance(custom, dict) and custom.get("uuid"):
                friendly_names[str(custom["uuid"])] = str(
                    custom.get("display_name") or "TMT gate"
                )

        devices: list[TmtDevice] = []
        skipped_no_uuid = 0
        skipped_no_endpoint = 0
        for bucket, role in (
            ("admin_devices", "admin"),
            ("user_devices", "user"),
            ("share_devices", "shared"),
        ):
            for raw in payload.get(bucket, []) or []:
                if not isinstance(raw, dict) or not raw.get("uuid"):
                    skipped_no_uuid += 1
                    continue
                device_uuid = str(raw["uuid"])
                device_type = str(raw.get("devies_type") or raw.get("device_type") or "")
                endpoint = str(raw.get("iot_endpoint") or "")
                if not endpoint:
                    skipped_no_endpoint += 1
                    continue
                devices.append(
                    TmtDevice(
                        name=friendly_names.get(
                            device_uuid, str(raw.get("name") or "TMT gate")
                        ),
                        uuid=device_uuid,
                        role=role,
                        device_type=device_type,
                        product_type=str(raw.get("product_type") or ""),
                        iot_endpoint=endpoint,
                    )
                )

        _LOGGER.warning(
            "TMTDIAG DEVICE_PARSE_RESULT usable_devices=%s skipped_no_uuid=%s "
            "skipped_no_iot_endpoint=%s roles=%s device_types=%s product_types=%s",
            len(devices),
            skipped_no_uuid,
            skipped_no_endpoint,
            [device.role for device in devices],
            [device.device_type for device in devices],
            [device.product_type for device in devices],
        )
        return devices

    async def async_bootstrap_aws(self, device: TmtDevice) -> TmtAwsCredentials:
        """Create one dedicated certificate and attach its device policy."""
        device_fp = _fingerprint(device.uuid)
        _LOGGER.warning(
            "TMTDIAG AWS_BOOTSTRAP_START device_uuid_sha256=%s role=%s "
            "device_type=%s product_type=%s iot_endpoint=%s",
            device_fp,
            device.role,
            device.device_type,
            device.product_type,
            device.iot_endpoint,
        )

        certificate = await self._request(
            "PUT", CERTIFICATE_PATH, json={"app": 0}, phase="aws_certificate"
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

        _LOGGER.warning(
            "TMTDIAG AWS_CERT_RESPONSE device_uuid_sha256=%s keys=%s "
            "private_key_present=%s certificate_pem_present=%s "
            "certificate_arn_present=%s endpoint=%s",
            device_fp,
            sorted(certificate.keys()),
            isinstance(private_key, str) and bool(private_key),
            isinstance(certificate_pem, str) and bool(certificate_pem),
            isinstance(certificate_arn, str) and bool(certificate_arn),
            endpoint,
        )

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
            phase="aws_policy",
        )
        thing_name = _value(policy, "thing_name", "thingName", "ThingName")
        if not isinstance(thing_name, str) or not thing_name:
            thing_name = device.uuid

        _LOGGER.warning(
            "TMTDIAG AWS_POLICY_RESPONSE device_uuid_sha256=%s keys=%s "
            "thing_name_sha256=%s",
            device_fp,
            sorted(policy.keys()),
            _fingerprint(thing_name),
        )

        return TmtAwsCredentials(
            private_key=private_key,
            certificate_pem=certificate_pem,
            certificate_arn=certificate_arn,
            endpoint=endpoint,
            thing_name=thing_name,
        )
