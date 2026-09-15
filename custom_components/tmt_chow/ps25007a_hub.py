"""PS25007/PS25007A AutoProduct parameter support with strict safety guards."""

from __future__ import annotations

from .const import ATTR_DEV_PARAM
from .controller_types import (
    CAPABILITY_EXTERNAL,
    CAPABILITY_PEDESTRIAN,
    FAMILY_SLIDING,
)
from .hub import TmtCommandError
from .model_parameter_schemas import parameter_schema_for
from .parameter_codec import ParameterTransport, is_editable_parameter
from .ps21050d_hub import TmtChowHub as BaseAliasHub
from .ps25007a_parameters import (
    APP_MODEL,
    CONTROLLER_TYPE,
    PARAMETER_COUNT,
    REFERENCE_SCHEMA_MODEL,
    PS25007AParameterError,
    encode_parameter_write,
    parse_parameter_response,
)


class TmtChowHub(BaseAliasHub):
    """Extend the hardened hub with the exact PS25007 -> PS25007A alias.

    The cloud account identity is PS25007 and the real controller reports
    PS25007A in DEV INFO.  The PS25007 AutoProduct Proposal and live hardware
    confirm a 17-slot RP,1/WP,1 layout matching the existing verified P500BU
    option schema.  Parameter writes are enabled only after the live PS25007A
    identity has been observed.

    Direct PED OPEN is intentionally unrelated to parameter support and remains
    blocked by pedestrian.py because real-hardware testing proved it unsafe on
    PS25007A.
    """

    def _is_ps25007a_profile(self) -> bool:
        return (
            self.configured_controller_type == APP_MODEL
            and self.parameter_model_type == CONTROLLER_TYPE
            and self.controller_type in {APP_MODEL, CONTROLLER_TYPE}
        )

    def _is_ps25007a_live_alias(self) -> bool:
        return (
            self.configured_controller_type == APP_MODEL
            and self.controller_type == CONTROLLER_TYPE
            and self.parameter_model_type == CONTROLLER_TYPE
        )

    def _set_controller_type(self, controller_type: str | None) -> None:
        normalized = (controller_type or "").strip().upper()

        if (
            self.configured_controller_type == APP_MODEL
            and normalized in {APP_MODEL, CONTROLLER_TYPE}
        ):
            self.controller_type = normalized
            self.controller_family = FAMILY_SLIDING
            # The Proposal declares Ext and PED Open.  Keep pedestrian absent
            # during the provisional account-only phase so no unsafe button can
            # be created before live DEV INFO confirms PS25007A.  Once live,
            # pedestrian.py still hard-blocks direct PED OPEN for this model.
            capabilities = {CAPABILITY_EXTERNAL}
            if normalized == CONTROLLER_TYPE:
                capabilities.add(CAPABILITY_PEDESTRIAN)
            self.controller_capabilities = frozenset(capabilities)
            self.parameter_model_type = CONTROLLER_TYPE
            self.parameter_model_source = (
                "ps25007_proposal_wire17_pending_live"
                if normalized == APP_MODEL
                else "ps25007a_proposal_wire17_verified"
            )
            self.model_parameter_schema = parameter_schema_for(REFERENCE_SCHEMA_MODEL)
            return

        super()._set_controller_type(controller_type)

    @property
    def parameter_schema_verified(self) -> bool:
        """Allow safe RP,1 reads for the exact configured PS25007 profile."""
        if self._is_ps25007a_profile():
            return (
                self.model_parameter_schema is not None
                and len(self.model_parameter_schema) == PARAMETER_COUNT
            )
        return super().parameter_schema_verified

    @property
    def parameter_write_schema_verified(self) -> bool:
        """Allow WP,1 only after the exact live PS25007A identity is known."""
        if self._is_ps25007a_live_alias():
            return self.parameter_schema_verified
        if self._is_ps25007a_profile():
            return False
        return super().parameter_write_schema_verified

    def _parameter_transport(self) -> ParameterTransport:
        if self._is_ps25007a_profile():
            return ParameterTransport(1, "RP,1", "ACK RP,1", "ACK WP")
        return super()._parameter_transport()

    def _decode_parameter_response(self, payload: str) -> tuple[int, ...] | None:
        if self._is_ps25007a_profile():
            return parse_parameter_response(payload)
        return super()._decode_parameter_response(payload)

    async def async_set_parameter(self, index: int, value: int) -> None:
        """Write one PS25007A setting with full-frame read-back verification."""
        if not self._is_ps25007a_live_alias():
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
            # Never write from stale Shadow state.  Read the complete current
            # frame from the controller immediately before constructing WP,1.
            current_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            current = self._decode_parameter_response(current_response)
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid PS25007A read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_parameter_write(values)
            except PS25007AParameterError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            # Exactly one write.  A timeout or lost ACK never resends WP,1.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # Require the entire 17-slot frame to match, not just the field
            # that was changed.  This detects any unexpected collateral change.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            if verified != values:
                raise TmtCommandError(
                    "PS25007A parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()
