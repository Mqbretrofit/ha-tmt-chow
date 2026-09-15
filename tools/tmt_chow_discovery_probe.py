#!/usr/bin/env python3
"""Privacy-safe TMT Chow device discovery probe.

This standalone helper reproduces only the login + device-list discovery used by
the Home Assistant integration. It does NOT request an AWS certificate, attach
an IoT policy, connect to MQTT, subscribe, publish, or send gate commands.

The generated JSON intentionally redacts credentials, UUIDs, IoT endpoints,
network details, custom names, and generic string values. Exact values are kept
only for a small allowlist of model/type/version fields useful for identifying
unsupported controller layouts.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASE_URL = "https://installer.tmt-automation.com/"
LOGIN_PATH = "v4.0/user/outh2/token/"
DEVICES_PATH = "v4.0/user/devices/"
OAUTH_CLIENT = (
    "pMFvOSB4KySGR7PDKfMklr4XxbWzyh1Qc0v7JX48:"
    "jNIe1wVDCu14C42U4Jg0CzTG1JobYnpvhhpVh10hwkZKZnP5dBS9kVhZjIxB6CfH"
    "r7eTGT3ccncBnwZeYoor5MbkfLmJphkyBRr5saWOPRaAteTuMELYYfWQKgrVIHH0"
)
DEFAULT_OUTPUT = "tmt_chow_discovery_probe.json"

SAFE_VALUE_KEYS = {
    "device_type",
    "devies_type",  # spelling used by the current TMT API/integration
    "product_type",
    "role",
    "model",
    "model_type",
    "controller_type",
    "controller_model",
    "hardware_version",
    "hw_version",
    "firmware_version",
    "fw_version",
    "uart_version",
    "wbt_version",
    "protocol_version",
    "version",
    "app_type",
    "app_type_index",
}

SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "privatekey",
    "certificate",
    "authorization",
)

IDENTIFIER_KEY_PARTS = (
    "uuid",
    "thing_name",
    "thingname",
    "device_id",
    "deviceid",
    "serial",
)

NETWORK_KEY_PARTS = (
    "endpoint",
    "hostname",
    "host",
    "ip",
    "ssid",
    "mac",
    "bssid",
)

CUSTOM_NAME_KEY_PARTS = (
    "display_name",
    "friendly_name",
    "nickname",
    "alias",
)

TYPE_HINT_PARTS = (
    "type",
    "model",
    "controller",
    "product",
    "version",
    "firmware",
    "hardware",
    "protocol",
    "role",
)


class ProbeError(RuntimeError):
    """Raised for expected probe failures."""


def _url(path: str) -> str:
    return BASE_URL.rstrip("/") + "/" + path.lstrip("/")


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    access_token: str | None = None,
    basic_auth: bool = False,
) -> tuple[int, dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ha-tmt-chow-discovery-probe/1",
    }
    if basic_auth:
        encoded = base64.b64encode(OAUTH_CLIENT.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    elif access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        _url(path),
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as err:
        if err.code in (400, 401, 403):
            raise ProbeError(
                f"TMT API rejected the request with HTTP {err.code}. "
                "Check the account credentials."
            ) from err
        raise ProbeError(f"TMT API returned HTTP {err.code}.") from err
    except urllib.error.URLError as err:
        raise ProbeError(f"Could not connect to the TMT API: {err.reason}") from err
    except TimeoutError as err:
        raise ProbeError("TMT API request timed out.") from err

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ProbeError("TMT API returned a non-JSON response.") from err

    if not isinstance(payload, dict):
        raise ProbeError("TMT API returned an unexpected JSON root type.")
    return status, payload


def _extract_access_token(payload: dict[str, Any]) -> str:
    for container in (payload, payload.get("data")):
        if isinstance(container, dict):
            value = container.get("access_token")
            if isinstance(value, str) and value:
                return value
    raise ProbeError("Login succeeded but no access token was present in the response.")


def _hash_marker(value: Any, label: str = "id") -> str:
    raw = str(value).encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"<redacted:{label}:sha256={digest}:len={len(str(value))}>"


def _key_contains(key: str, parts: tuple[str, ...]) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in parts)


def _sanitize_scalar(key: str, value: Any) -> Any:
    lowered = key.lower()

    if value is None or isinstance(value, bool):
        return value

    if _key_contains(lowered, SECRET_KEY_PARTS):
        return "<redacted:secret>"

    if _key_contains(lowered, NETWORK_KEY_PARTS):
        return f"<redacted:network:{type(value).__name__}>"

    if _key_contains(lowered, IDENTIFIER_KEY_PARTS):
        return _hash_marker(value, "identifier")

    if _key_contains(lowered, CUSTOM_NAME_KEY_PARTS) or lowered == "name":
        return f"<redacted:name:{type(value).__name__}>"

    if lowered in SAFE_VALUE_KEYS:
        if isinstance(value, (str, int, float)):
            return value
        return f"<{type(value).__name__}>"

    if isinstance(value, (int, float)):
        if lowered == "id" or lowered.endswith("_id"):
            return _hash_marker(value, "identifier")
        return value

    if isinstance(value, str):
        return f"<redacted:string:len={len(value)}>"

    return f"<{type(value).__name__}>"


def sanitize(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(child_key): sanitize(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, key=key) for item in value]
    return _sanitize_scalar(key, value)


def _walk(
    value: Any,
    predicate: Callable[[str, Any], bool],
    *,
    path: str = "$",
) -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if predicate(str(key), child):
                found.append((child_path, str(key), child))
            found.extend(_walk(child, predicate, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk(child, predicate, path=f"{path}[{index}]"))
    return found


def _path_records(
    value: Any,
    predicate: Callable[[str, Any], bool],
    *,
    include_safe_value: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path, key, child in _walk(value, predicate):
        record: dict[str, Any] = {
            "path": path,
            "key": key,
            "value_type": type(child).__name__,
            "present": child not in (None, "", [], {}),
        }
        if include_safe_value and key.lower() in SAFE_VALUE_KEYS:
            record["value"] = _sanitize_scalar(key, child)
        records.append(record)
    return records


def _device_summary(bucket: str, index: int, item: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "bucket": bucket,
        "index": index,
        "item_type": type(item).__name__,
    }
    if not isinstance(item, dict):
        return summary

    summary.update(
        {
            "direct_fields": sorted(str(key) for key in item.keys()),
            "direct_uuid_present": bool(item.get("uuid")),
            "direct_iot_endpoint_present": bool(item.get("iot_endpoint")),
            "identifier_paths": _path_records(
                item,
                lambda key, _value: _key_contains(key, IDENTIFIER_KEY_PARTS),
            ),
            "endpoint_paths": _path_records(
                item,
                lambda key, _value: _key_contains(key, NETWORK_KEY_PARTS),
            ),
            "type_model_version_paths": _path_records(
                item,
                lambda key, _value: _key_contains(key, TYPE_HINT_PARTS),
                include_safe_value=True,
            ),
        }
    )
    return summary


def analyze_devices(payload: dict[str, Any]) -> dict[str, Any]:
    list_fields = {
        key: len(value)
        for key, value in payload.items()
        if isinstance(value, list)
    }
    known_buckets = ("admin_devices", "user_devices", "share_devices")
    devices: list[dict[str, Any]] = []

    for bucket in known_buckets:
        value = payload.get(bucket)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            devices.append(_device_summary(bucket, index, item))

    parser_eligible = sum(
        1
        for device in devices
        if device.get("direct_uuid_present") and device.get("direct_iot_endpoint_present")
    )

    return {
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "top_level_list_counts": list_fields,
        "known_device_buckets_present": [
            bucket for bucket in known_buckets if bucket in payload
        ],
        "known_device_items_total": len(devices),
        "items_matching_current_integration_requirements": parser_eligible,
        "items_rejected_by_current_integration_requirements": len(devices)
        - parser_eligible,
        "device_items": devices,
    }


def build_report(
    *,
    login_status: int,
    devices_status: int,
    devices_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "probe": {
            "name": "ha-tmt-chow discovery probe",
            "version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "safety": {
                "login_request_sent": True,
                "device_list_request_sent": True,
                "certificate_request_sent": False,
                "policy_request_sent": False,
                "mqtt_connected": False,
                "mqtt_subscribed": False,
                "mqtt_published": False,
                "gate_command_sent": False,
            },
            "privacy": {
                "access_token_written": False,
                "password_written": False,
                "uuid_values_hashed": True,
                "iot_endpoints_redacted": True,
                "generic_strings_redacted": True,
                "custom_names_redacted": True,
                "exact_values_allowlisted_for_model_type_version_fields": True,
            },
        },
        "http": {
            "login_status": login_status,
            "devices_status": devices_status,
        },
        "analysis": analyze_devices(devices_payload),
        "sanitized_devices_response": sanitize(devices_payload),
    }


def run_probe(email: str, password: str) -> dict[str, Any]:
    login_status, login_payload = _request(
        "POST",
        LOGIN_PATH,
        body={
            "username": email,
            "password": password,
            "grant_type": "password",
            "scope": "user",
            "app_type_index": 1,
        },
        basic_auth=True,
    )
    access_token = _extract_access_token(login_payload)
    devices_status, devices_payload = _request(
        "GET",
        DEVICES_PATH,
        access_token=access_token,
    )
    return build_report(
        login_status=login_status,
        devices_status=devices_status,
        devices_payload=devices_payload,
    )


def _self_test() -> None:
    sample = {
        "admin_devices": [
            {
                "uuid": "very-secret-uuid",
                "iot_endpoint": "abc123-ats.iot.eu-central-1.amazonaws.com",
                "devies_type": "PS99999",
                "product_type": "TEST_PRODUCT",
                "name": "Home gate",
                "nested": {
                    "controller_model": "Terrier 200 Pro",
                    "device_id": 123456,
                    "wifi_ssid": "PrivateWifi",
                    "mystery": "do-not-leak",
                },
            }
        ],
        "custom_info": [
            {"uuid": "very-secret-uuid", "display_name": "Driveway"}
        ],
    }
    report = build_report(
        login_status=200,
        devices_status=200,
        devices_payload=sample,
    )
    dumped = json.dumps(report, ensure_ascii=False)

    forbidden = (
        "very-secret-uuid",
        "abc123-ats.iot.eu-central-1.amazonaws.com",
        "Home gate",
        "PrivateWifi",
        "do-not-leak",
        "Driveway",
    )
    leaked = [value for value in forbidden if value in dumped]
    if leaked:
        raise AssertionError(f"Self-test detected privacy leak(s): {leaked}")

    if "PS99999" not in dumped or "TEST_PRODUCT" not in dumped:
        raise AssertionError("Self-test lost allowlisted model/type information.")

    analysis = report["analysis"]
    if analysis["items_matching_current_integration_requirements"] != 1:
        raise AssertionError("Self-test parser eligibility result is wrong.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Privacy-safe TMT Chow device discovery probe for Home Assistant "
            "integration troubleshooting."
        )
    )
    parser.add_argument(
        "--email",
        help="TMT Chow account email. If omitted, the script prompts for it.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the built-in sanitizer test without contacting TMT.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        _self_test()
        print("Self-test passed: no sample secrets leaked.")
        return 0

    email = args.email or input("TMT Chow email: ").strip()
    if not email:
        print("Error: email is required.", file=sys.stderr)
        return 2

    password = getpass.getpass("TMT Chow password: ")
    if not password:
        print("Error: password is required.", file=sys.stderr)
        return 2

    try:
        report = run_probe(email, password)
    except ProbeError as err:
        print(f"Probe failed: {err}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    analysis = report["analysis"]
    print(f"Wrote privacy-safe report to: {output}")
    print(
        "Known device items: "
        f"{analysis['known_device_items_total']}; "
        "matching current integration requirements: "
        f"{analysis['items_matching_current_integration_requirements']}; "
        "rejected: "
        f"{analysis['items_rejected_by_current_integration_requirements']}"
    )
    print(
        "Please review the JSON before uploading it to GitHub. "
        "The probe never writes the password or access token."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
