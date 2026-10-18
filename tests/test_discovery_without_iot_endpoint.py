"""Regression tests for account discovery without a device-list IoT endpoint."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.api import TmtChowApi
from custom_components.tmt_chow.const import DEVICES_PATH


def test_discovery_keeps_device_without_iot_endpoint() -> None:
    """A valid account device must not be discarded only because endpoint is null."""
    api = TmtChowApi(None)  # type: ignore[arg-type]

    async def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == DEVICES_PATH
        return {
            "admin_devices": [
                {
                    "uuid": "ps19001-device",
                    "uuid_type": "5",
                    "devies_type": "PS19001",
                    "product_type": "108",
                    "iot_endpoint": None,
                }
            ],
            "user_devices": [
                {
                    "uuid": "existing-endpoint-device",
                    "uuid_type": "1",
                    "devies_type": "PS22027",
                    "product_type": "200",
                    "iot_endpoint": "example-ats.iot.eu-central-1.amazonaws.com",
                }
            ],
            "share_devices": [
                {
                    "devies_type": "PS19001",
                    "product_type": "108",
                    "iot_endpoint": None,
                }
            ],
            "custom_info": [
                {
                    "uuid": "ps19001-device",
                    "display_name": "Driveway gate",
                }
            ],
        }

    api._request = fake_request  # type: ignore[method-assign]

    devices = asyncio.run(api.async_get_devices())

    assert len(devices) == 2

    discovered = devices[0]
    assert discovered.uuid == "ps19001-device"
    assert discovered.uuid_type == "5"
    assert discovered.name == "Driveway gate"
    assert discovered.role == "admin"
    assert discovered.device_type == "PS19001"
    assert discovered.product_type == "108"
    assert discovered.iot_endpoint == ""

    existing = devices[1]
    assert existing.uuid == "existing-endpoint-device"
    assert existing.uuid_type == "1"
    assert existing.role == "user"
    assert existing.iot_endpoint == "example-ats.iot.eu-central-1.amazonaws.com"


def test_discovery_recognizes_nested_shared_gates_issue73() -> None:
    """Shared metadata is nested, and user labels live on the wrapper."""
    api = TmtChowApi(None)  # type: ignore[arg-type]

    async def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        assert method == "GET" and path == DEVICES_PATH
        return {
            "admin_devices": [
                {
                    "uuid": "flat-admin",
                    "devies_type": "PS19001",
                    "uuid_type": "5",
                    "iot_endpoint": "mqtt.example.invalid",
                }
            ],
            "user_devices": [],
            "share_devices": [
                {
                    "custom_user_display_name": "Shared driveway",
                    "devies_info": {
                        "uuid": "12345678901234567890",
                        "devies_type": "PS20005",
                        "product_type": "108",
                        "uuid_type": "1",
                        "iot_endpoint": None,
                    },
                },
                {
                    "custom_user_display_name": "Shared garage",
                    "devies_info": {
                        "uuid": "shared-mqtt",
                        "device_type": "PS20005B",
                        "product_type": "108",
                        "uuid_type": "5",
                        "iot_endpoint": "shared.example.invalid",
                    },
                },
                {"devies_info": {"device_type": "PS20005"}},
                {"devies_info": None},
                {"uuid": None},
            ],
            "custom_info": [
                {"uuid": "flat-admin", "display_name": "Owner gate"}
            ],
        }

    api._request = fake_request  # type: ignore[method-assign]
    devices = asyncio.run(api.async_get_devices())
    assert len(devices) == 3

    flat, shared_native, shared_mqtt = devices
    assert (flat.name, flat.role, flat.uuid_type, flat.iot_endpoint) == (
        "Owner gate", "admin", "5", "mqtt.example.invalid"
    )
    assert (
        shared_native.name,
        shared_native.role,
        shared_native.uuid,
        shared_native.device_type,
        shared_native.product_type,
        shared_native.uuid_type,
        shared_native.iot_endpoint,
    ) == (
        "Shared driveway", "shared", "12345678901234567890",
        "PS20005", "108", "1", ""
    )
    assert (shared_mqtt.name, shared_mqtt.device_type, shared_mqtt.uuid_type) == (
        "Shared garage", "PS20005B", "5"
    )
