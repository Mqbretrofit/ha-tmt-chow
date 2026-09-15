"""PS25007/PS25007A AutoProduct parameter support with strict safety guards."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import time
from typing import Any

from .const import ATTR_DEV_PARAM, DEFAULT_SOURCE_TAG
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

_PED_TEST_CAPTURE_SECONDS = 35.0
_PED_TEST_MAX_MESSAGES = 64


class TmtChowHub(BaseAliasHub):
    """Extend the hardened hub with the exact PS25007 -> PS25007A alias.

    The cloud account identity is PS25007 and the real controller reports
    PS25007A in DEV INFO. The PS25007 AutoProduct Proposal and live hardware
    confirm a 17-slot RP,1/WP,1 layout matching the existing verified P500BU
    option schema. Parameter writes are enabled only after the live PS25007A
    identity has been observed.

    Normal direct PED OPEN stays blocked by pedestrian.py. This experimental
    build adds only a separate, explicitly confirmed one-shot test path for the
    exact PS25007 -> PS25007A live alias using a non-anonymous account-derived
    source tag. It never enables the normal pedestrian button or strategy.
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
            # The Proposal declares Ext and PED Open. Keep pedestrian absent
            # during the provisional account-only phase so no unsafe button can
            # be created before live DEV INFO confirms PS25007A. Once live,
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

    def _identified_source_tag(self) -> str | None:
        """Return a non-anonymous UART-v1 source tag, or None if unavailable."""
        tag = str(self._source_tag or "").strip().upper()
        if tag == DEFAULT_SOURCE_TAG:
            return None
        if re.fullmatch(r"P[0-9A-F]{7,}", tag) is None:
            return None
        return tag

    def _ped_test_capture_active(self) -> bool:
        until = getattr(self, "_ped_test_capture_until_monotonic", 0.0)
        return bool(until and time.monotonic() <= until)

    def _append_ped_test_trace(self, topic: str, payload: str) -> None:
        if not self._ped_test_capture_active():
            return

        trace = getattr(self, "_ped_test_trace", None)
        if trace is None:
            trace = []
            self._ped_test_trace = trace
        if len(trace) >= _PED_TEST_MAX_MESSAGES:
            return

        if topic == self.tx_topic:
            label = "wbt01Tx"
        elif topic == self.position_topic:
            label = "position"
        elif topic == self.shadow_documents_topic:
            label = "shadow/update/documents"
        elif topic == self.shadow_get_accepted_topic:
            label = "shadow/get/accepted"
        else:
            label = topic

        trace.append(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "topic": label,
                "payload": payload[:4096],
            }
        )

    async def _async_message(self, topic: str, payload: str) -> None:
        self._append_ped_test_trace(topic, payload)
        await super()._async_message(topic, payload)

        if self._ped_test_capture_active():
            self._ped_test_last_position = self.position
            self._ped_test_last_movement = self.movement
            self._ped_test_last_is_operating = self.is_operating

    @property
    def ps25007a_ped_test_diagnostics(self) -> dict[str, Any]:
        """Return isolated diagnostics for the one-shot experimental test."""
        active = self._ped_test_capture_active()
        status = getattr(self, "_ped_test_status", "idle")
        if status == "observing" and not active:
            status = "complete"

        return {
            "enabled_in_build": True,
            "normal_pedestrian_strategy": self.pedestrian_strategy,
            "configured_controller_type": self.configured_controller_type,
            "live_controller_type": self.controller_type,
            "source_tag": self._source_tag,
            "identified_source_tag": self._identified_source_tag() is not None,
            "required_confirmation": (
                f"PED OPEN {self._source_tag}"
                if self._identified_source_tag() is not None
                else None
            ),
            "status": status,
            "capture_active": active,
            "capture_seconds": _PED_TEST_CAPTURE_SECONDS,
            "started_at_utc": getattr(self, "_ped_test_started_at_utc", None),
            "start_position": getattr(self, "_ped_test_start_position", None),
            "start_is_operating": getattr(self, "_ped_test_start_is_operating", None),
            "ack_received": getattr(self, "_ped_test_ack_received", None),
            "telemetry_confirmed_without_ack": getattr(
                self,
                "_ped_test_telemetry_confirmed_without_ack",
                None,
            ),
            "last_position": getattr(self, "_ped_test_last_position", None),
            "last_movement": getattr(self, "_ped_test_last_movement", None),
            "last_is_operating": getattr(
                self,
                "_ped_test_last_is_operating",
                None,
            ),
            "preflight_parameters": getattr(
                self,
                "_ped_test_preflight_parameters",
                None,
            ),
            "error": getattr(self, "_ped_test_error", None),
            "trace": list(getattr(self, "_ped_test_trace", [])),
        }

    async def async_ps25007a_pedestrian_test(self, confirmation: str) -> None:
        """Send exactly one controlled PED OPEN on the verified live alias.

        This method intentionally bypasses the normal pedestrian strategy only
        for this explicit test service. It requires the exact account/live model
        pair, a non-anonymous source tag, a fully closed and stopped gate, and a
        confirmation phrase containing the runtime source tag. No movement
        command is retried and no follow-up movement command is sent.
        """
        if not self._is_ps25007a_live_alias():
            raise TmtCommandError(
                "The controlled test is restricted to configured PS25007 with live PS25007A",
                translation_key="unsupported_controller",
            )

        source_tag = self._identified_source_tag()
        if source_tag is None:
            raise TmtCommandError(
                "The controlled test requires a non-anonymous account-derived source tag",
                translation_key="unsupported_controller",
            )

        expected_confirmation = f"PED OPEN {source_tag}"
        if confirmation.strip().upper() != expected_confirmation:
            raise TmtCommandError(
                f"Confirmation must be exactly: {expected_confirmation}",
                translation_key="command_failed",
            )

        if self.position != 0 or self.is_operating is not False:
            raise TmtCommandError(
                "The controlled test requires the gate to be fully closed and stopped",
                translation_key="command_failed",
            )

        if self._ped_test_capture_active():
            raise TmtCommandError(
                "A PS25007A pedestrian test observation window is still active",
                translation_key="command_failed",
            )

        self._ped_test_trace = []
        self._ped_test_started_at_utc = datetime.now(timezone.utc).isoformat()
        self._ped_test_capture_until_monotonic = (
            time.monotonic() + _PED_TEST_CAPTURE_SECONDS
        )
        self._ped_test_status = "preflight"
        self._ped_test_error = None
        self._ped_test_ack_received = None
        self._ped_test_telemetry_confirmed_without_ack = None
        self._ped_test_start_position = self.position
        self._ped_test_start_is_operating = self.is_operating
        self._ped_test_last_position = self.position
        self._ped_test_last_movement = self.movement
        self._ped_test_last_is_operating = self.is_operating

        try:
            # Read-only controller preflight immediately before the one movement
            # command. This also proves the exact 17-slot PS25007A profile is
            # still responsive without modifying any setting.
            await self.async_refresh_parameters()
            if self.parameters is None or len(self.parameters) != PARAMETER_COUNT:
                raise TmtCommandError(
                    "PS25007A parameter preflight did not return the expected 17-slot frame",
                    translation_key="invalid_parameter_set",
                )
            self._ped_test_preflight_parameters = tuple(self.parameters)

            self._ped_test_status = "sending"
            acknowledged = await self._async_command(
                "PED OPEN",
                "ACK PED OPEN",
                motion_direction="opening",
            )
            self._ped_test_ack_received = acknowledged
            self._ped_test_telemetry_confirmed_without_ack = not acknowledged
            self._ped_test_status = "observing"
        except TmtCommandError as err:
            self._ped_test_error = str(err)
            self._ped_test_status = "error"
            raise

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
            # Never write from stale Shadow state. Read the complete current
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

            # Exactly one write. A timeout or lost ACK never resends WP,1.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # Require the entire 17-slot frame to match, not just the field
            # that was changed. This detects any unexpected collateral change.
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
