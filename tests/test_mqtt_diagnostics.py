"""Regression tests for AWS IoT MQTT diagnostic messages."""

from custom_components.tmt_chow.mqtt import _describe_exception


def test_timeout_error_never_formats_as_blank_message() -> None:
    assert _describe_exception(TimeoutError()) == "TimeoutError"


def test_exception_type_is_preserved_with_message() -> None:
    assert _describe_exception(OSError("network unreachable")) == (
        "OSError: network unreachable"
    )
