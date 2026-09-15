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
                    "devies_type": "PS19001",
                    "product_type": "108",
                    "iot_endpoint": None,
                }
            ],
            "user_devices": [
                {
                    "uuid": "existing-endpoint-device",
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
    assert discovered.name == "Driveway gate"
    assert discovered.role == "admin"
    assert discovered.device_type == "PS19001"
    assert discovered.product_type == "108"
    assert discovered.iot_endpoint == ""

    existing = devices[1]
    assert existing.uuid == "existing-endpoint-device"
    assert existing.role == "user"
    assert existing.iot_endpoint == "example-ats.iot.eu-central-1.amazonaws.com"
