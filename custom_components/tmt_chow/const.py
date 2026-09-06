"""Constants for the TMT Chow integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "tmt_chow"
PLATFORMS: Final = [
    Platform.COVER,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SENSOR,
]

BASE_URL: Final = "https://installer.tmt-automation.com/"
LOGIN_PATH: Final = "v4.0/user/outh2/token/"
DEVICES_PATH: Final = "v4.0/user/devices/"
CERTIFICATE_PATH: Final = "v4.0/devices/iot/user/certificate/"
POLICY_PATH: Final = "v4.0/devices/iot/device/policy/"

OAUTH_CLIENT: Final = (
    "pMFvOSB4KySGR7PDKfMklr4XxbWzyh1Qc0v7JX48:"
    "jNIe1wVDCu14C42U4Jg0CzTG1JobYnpvhhpVh10hwkZKZnP5dBS9kVhZjIxB6CfH"
    "r7eTGT3ccncBnwZeYoor5MbkfLmJphkyBRr5saWOPRaAteTuMELYYfWQKgrVIHH0"
)

CONF_UUID: Final = "uuid"
CONF_ENDPOINT: Final = "endpoint"
CONF_THING_NAME: Final = "thing_name"
CONF_CERTIFICATE_PEM: Final = "certificate_pem"
CONF_PRIVATE_KEY: Final = "private_key"
CONF_CERTIFICATE_ARN: Final = "certificate_arn"
CONF_DEVICE_TYPE: Final = "device_type"
CONF_PRODUCT_TYPE: Final = "product_type"
CONF_ROLE: Final = "role"
CONF_SOURCE_TAG: Final = "source_tag"

DEFAULT_SOURCE_TAG: Final = "P9999999"
MQTT_PORT: Final = 8883
MQTT_KEEPALIVE: Final = 30
MQTT_PING_TIMEOUT: Final = 10
MQTT_RECONNECT_SECONDS: Final = 3
MQTT_AVAILABILITY_GRACE_SECONDS: Final = 90
SHADOW_REFRESH_SECONDS: Final = 15
COMMAND_TIMEOUT: Final = 10
PARAMETER_REFRESH_SECONDS: Final = 300
PARAMETER_BOOTSTRAP_RETRY_SECONDS: Final = 15

ATTR_DEV_STATUS: Final = "dev_status"
ATTR_DEV_INFO: Final = "dev_info"
ATTR_DEV_PARAM: Final = "dev_param"
ATTR_UART_VERSION: Final = "uart_version"
ATTR_WBT_VERSION: Final = "wbt_version"
ATTR_LOCAL_IP: Final = "local_ip"
ATTR_WIFI_SSID: Final = "wifi_ssid"
ATTR_LAST_RESPONSE: Final = "last_response"
