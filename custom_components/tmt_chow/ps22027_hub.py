"""Verified PS22027 write support layered on the hardened TMT hub."""

from __future__ import annotations

from .const import ATTR_DEV_PARAM
from .hub import TmtCommandError
from .parameter_codec import is_editable_parameter
from .ps21050d_hub import TmtChowHub as BaseTmtChowHub
from .ps22027_parameters import (
    CONTROLLER_TYPE,
    PS22027ParameterError,
    encode_parameter_write,
    parse_parameter_response,
)


class TmtChowHub(BaseTmtChowHub):
    """Add validated single-write/read-back handling for live PS22027 hardware."""

    def _is_ps22027_verified_profile(self) -> bool:
        return (
            self.controller_type == CONTROLLER_TYPE
            and self.parameter_model_type == CONTROLLER_TYPE
            and self.parameter_model_source == "ps22027_wire20_verified"
        )

    def _set_controller_type(self, controller_type: str | None) -> None:
        super()._set_controller_type(controller_type)
        if (
            self.controller_type == CONTROLLER_TYPE
            and self.parameter_model_type == CONTROLLER_TYPE
            and self.parameter_model_source == "ps22027_wire20_read_only"
        ):
            self.parameter_model_source = "ps22027_wire20_verified"

    def _decode_parameter_response(self, payload: str) -> tuple[int, ...] | None:
        if self._is_ps22027_verified_profile():
            return parse_parameter_response(payload)
        return super()._decode_parameter_response(payload)

    @property
    def parameter_write_schema_verified(self) -> bool:
        """Enable writes only for the live-verified PS22027 20-slot profile."""
        if self._is_ps22027_verified_profile():
            return True
        return super().parameter_write_schema_verified

    async def async_set_parameter(self, index: int, value: int) -> None:
        """Write one PS22027 field as one full WP,1 frame and verify by RP,1."""
        if not self._is_ps22027_verified_profile():
            await super().async_set_parameter(index, value)
            return

        schema = self.model_parameter_schema
        if schema is None or not 0 <= index < len(schema):
            raise TmtCommandError(
                "Unknown gate parameter",
                translation_key="unknown_parameter",
            )
        if not is_editable_parameter(schema[index]):
            raise TmtCommandError(
                "This vendor parameter is not directly writable",
                translation_key="unknown_parameter",
            )

        transport = self._parameter_transport()
        async with self._transaction_lock:
            # Always start from a fresh complete 20-value controller frame.
            current_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            current = self._decode_parameter_response(current_response)
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid PS22027 read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_parameter_write(values)
            except PS22027ParameterError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            # Never resend a WP,1 command automatically. A timeout must be
            # resolved by the explicit read-back below or by a later retry.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # Require the exact requested raw slot to be returned by a fresh RP,1.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            if verified is None or verified[index] != int(value):
                raise TmtCommandError(
                    "PS22027 parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()
