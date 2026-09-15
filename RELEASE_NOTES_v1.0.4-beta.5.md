# TMT Chow v1.0.4-beta.5

## Fixed

- Account discovery no longer discards otherwise valid devices when the device-list response contains `iot_endpoint: null`.
- This fixes discovery for observed PS19001 / `product_type: 108` responses where the UUID and model information are present but the IoT endpoint is not returned by the device-list API.
- Existing devices that already include an IoT endpoint keep the same discovery behavior.

## Safety / scope

- AWS certificate and policy bootstrap behavior is unchanged.
- MQTT connection, subscription, publishing, and gate-command logic are unchanged.
- The endpoint is still required before AWS bootstrap can complete; when it is absent from the device list, the existing certificate response remains the next source for it.

## Tests

- Added a regression test covering an `admin_devices` entry with a UUID, `PS19001`, `product_type: 108`, and `iot_endpoint: null`.
- The test also verifies that an existing endpoint-bearing device is still discovered unchanged and that entries without a UUID remain ignored.
