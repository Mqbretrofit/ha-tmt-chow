"""PS21050D live-identity alias support derived from the vendor Android app."""

from __future__ import annotations

from .const import ATTR_DEV_PARAM
from .controller_types import controller_capabilities, controller_family
from .hub import TmtChowHub as BaseTmtChowHub, TmtCommandError
from .parameter_codec import is_editable_parameter
from .ps21050d_parameters import (
    APP_MODEL,
    APP_PARAMETERS,
    CONTROLLER_TYPE,
    PS21050DParameterError,
    encode_parameter_write,
)


class TmtChowHub(BaseTmtChowHub):
    """Use the official PS21050 app profile for live PS21050D hardware.

    TMT Chow 3.1.4 contains a PS21050 product implementation but no separate
    PS21050D implementation. The account API identifies this controller as
    PS21050, while live DEV INFO reports PS21050D. Preserve the concrete live
    identity but use the app's family/capability metadata and exact 20-value
    RP,1/WP,1 parameter layout for this alias pair.
    """

    def _is_ps21050d_alias(self) -> bool:
        return (
            self.controller_type == CONTROLLER_TYPE
            and self.configured_controller_type == APP_MODEL
        )

    def _set_controller_type(self, controller_type: str | None) -> None:
        normalized = (controller_type or "").strip().upper()
        if normalized == CONTROLLER_TYPE and self.configured_controller_type == APP_MODEL:
            self.controller_type = CONTROLLER_TYPE
            self.controller_family = controller_family(APP_MODEL)
            self.controller_capabilities = controller_capabilities(APP_MODEL)
            self.parameter_model_type = CONTROLLER_TYPE
            self.parameter_model_source = "apk_ps21050_alias"
            self.model_parameter_schema = APP_PARAMETERS
            return
        super()._set_controller_type(controller_type)

    @property
    def parameter_write_schema_verified(self) -> bool:
        """Allow writes only for the exact app-proven PS21050D/PS21050 alias."""
        if self._is_ps21050d_alias():
            return self.parameter_schema_verified
        return super().parameter_write_schema_verified

    async def async_set_parameter(self, index: int, value: int) -> None:
        """Write one PS21050D field through the vendor 20-value WP,1 frame."""
        if not self._is_ps21050d_alias():
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
            current_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            current = self._decode_parameter_response(current_response)
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid PS21050D read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_parameter_write(values)
            except PS21050DParameterError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            # Deliberately one write only. A timeout never resends WP,1.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # Read back the whole vendor frame and require the requested raw
            # field to match before accepting the setting in Home Assistant.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            if verified is None or verified[index] != int(value):
                raise TmtCommandError(
                    "PS21050D parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()
