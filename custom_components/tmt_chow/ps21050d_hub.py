"""Controller alias support plus runtime gate-state hardening."""

from __future__ import annotations

import time

from .const import ATTR_DEV_PARAM
from .controller_types import controller_capabilities, controller_family
from .hub import TmtChowHub as BaseTmtChowHub, TmtCommandError
from .parameter_codec import is_editable_parameter
from .pedestrian import (
    PEDESTRIAN_STRATEGY_NONE,
    PEDESTRIAN_STRATEGY_PED_OPEN,
    PEDESTRIAN_STRATEGY_RELAY4,
    pedestrian_strategy_for,
)
from .ps21050d_parameters import (
    APP_MODEL,
    APP_PARAMETERS,
    CONTROLLER_TYPE,
    PS21050DParameterError,
    encode_parameter_write,
)
from .ps22027_parameters import (
    APP_PARAMETERS as PS22027_PARAMETERS,
    CONTROLLER_TYPE as PS22027,
    PS22027ParameterError,
    encode_parameter_write as encode_ps22027_parameter_write,
    parse_parameter_response as parse_ps22027_parameter_response,
)

_PS20005_APP_MODEL = "PS20005"
_PS20005A_CONTROLLER_TYPE = "PS20005A"
_PS20040_APP_MODEL = "PS20040"
_PS20040D_CONTROLLER_TYPE = "PS20040D"
_STALE_STOP_DIRECTION_GUARD_SECONDS = 30.0


class TmtChowHub(BaseTmtChowHub):
    """Runtime hub with verified app/live aliases and stale-stop protection.

    TMT Chow 3.1.4 contains a PS21050 product implementation but no separate
    PS21050D implementation. The account API identifies this controller as
    PS21050, while live DEV INFO reports PS21050D. Preserve the concrete live
    identity but use the app's family/capability metadata and exact 20-value
    RP,1/WP,1 parameter layout for this alias pair.

    PS20040D is the same kind of app/live identity split: the account reports
    PS20040 while live DEV INFO reports PS20040D. For this exact pair, reuse
    the APK-derived PS20040 family, UI capabilities and RP,1/WP,1 codec. The
    write path still performs the normal read-before-write and mandatory
    read-back verification, and it never automatically retries a parameter
    write.

    PS20005A is an observed live/controller identity variant of the APK-listed
    PS20005 swing controller. Reuse only PS20005 family/UI capabilities for
    this exact alias, without borrowing a parameter codec or applying a broad
    suffix-stripping rule. This exposes the verified pedestrian capability
    while preserving the concrete PS20005A device identity.

    PS22027 uses its live-verified 20-slot RP,1/WP,1 profile. The generated APK
    matrix contains two inherited P190 current helper entries before the real
    20 wire slots, but live hardware proved those helpers are not separate
    RP,1 fields. Hall Sensor mode uses the APK P190 Hall-current table for the
    two current slots. Writes always read first, send exactly one full WP,1
    frame, then require the complete 20-slot frame to match on read-back.

    The pedestrian command path is strategy-gated. Direct PED OPEN is blocked
    for controller identities with real-hardware unsafe evidence (currently
    PS25007A), while RELAY4 remains disabled until a concrete controller has
    verified FunctionSet/hardware evidence.

    The vendor Shadow may also publish a stale stopped DEV STATUS position
    immediately after the dedicated /position topic has already reached 0 or
    100. Keep the last proven motion direction briefly so that late stale
    status cannot flip a just-closed gate back to open (or vice versa).
    """

    def _is_ps21050d_alias(self) -> bool:
        return (
            self.controller_type == CONTROLLER_TYPE
            and self.configured_controller_type == APP_MODEL
        )

    def _is_ps20040d_alias(self) -> bool:
        return (
            self.controller_type == _PS20040D_CONTROLLER_TYPE
            and self.configured_controller_type == _PS20040_APP_MODEL
        )

    def _is_ps22027_verified_profile(self) -> bool:
        return (
            self.controller_type == PS22027
            and self.parameter_model_type == PS22027
            and self.parameter_model_source == "ps22027_wire20_verified"
        )

    @property
    def pedestrian_strategy(self) -> str:
        """Return the currently permitted pedestrian command strategy."""
        return pedestrian_strategy_for(
            self.controller_type,
            self.controller_capabilities,
        )

    def _set_controller_type(self, controller_type: str | None) -> None:
        normalized = (controller_type or "").strip().upper()

        if (
            normalized == _PS20040D_CONTROLLER_TYPE
            and self.configured_controller_type == _PS20040_APP_MODEL
        ):
            # Let the base hub select the configured PS20040 parameter schema
            # and codec, then restore the APK-derived family/capabilities for
            # the concrete live D identity.
            super()._set_controller_type(controller_type)
            self.controller_family = controller_family(_PS20040_APP_MODEL)
            self.controller_capabilities = controller_capabilities(_PS20040_APP_MODEL)
            self.parameter_model_source = "apk_ps20040_alias"
            return

        if normalized == CONTROLLER_TYPE and self.configured_controller_type == APP_MODEL:
            self.controller_type = CONTROLLER_TYPE
            self.controller_family = controller_family(APP_MODEL)
            self.controller_capabilities = controller_capabilities(APP_MODEL)
            self.parameter_model_type = CONTROLLER_TYPE
            self.parameter_model_source = "apk_ps21050_alias"
            self.model_parameter_schema = APP_PARAMETERS
            return

        super()._set_controller_type(controller_type)

        if normalized == _PS20005A_CONTROLLER_TYPE:
            # Exact capability alias only. Do not borrow a PS20005 parameter
            # schema and do not strip arbitrary model suffixes globally.
            self.controller_family = controller_family(_PS20005_APP_MODEL)
            self.controller_capabilities = controller_capabilities(_PS20005_APP_MODEL)
            return

        if self.controller_type == PS22027 and self.parameter_model_type == PS22027:
            self.model_parameter_schema = PS22027_PARAMETERS
            self.parameter_model_source = "ps22027_wire20_verified"

    def _decode_parameter_response(self, payload: str) -> tuple[int, ...] | None:
        if self._is_ps22027_verified_profile():
            return parse_ps22027_parameter_response(payload)
        return super()._decode_parameter_response(payload)

    def _remember_motion_direction(self, direction: str) -> None:
        if direction not in ("opening", "closing"):
            return
        self._last_completed_motion_direction = direction
        self._last_completed_motion_monotonic = time.monotonic()

    def _apply_position(self, position: int, *, derive_movement: bool = True) -> None:
        """Remember the proven live direction even when an endpoint clears movement."""
        old_position = self.position
        prior_movement = self.movement
        super()._apply_position(position, derive_movement=derive_movement)

        if not derive_movement or old_position is None or self.position is None:
            return
        if self.position > old_position:
            self._remember_motion_direction("opening")
        elif self.position < old_position:
            self._remember_motion_direction("closing")
        elif prior_movement in ("opening", "closing") and self.position in (0, 100):
            self._remember_motion_direction(prior_movement)

    def _status_position_is_plausible(self, status_position: int) -> bool:
        """Reject a late stale stop position even after endpoint motion was cleared."""
        if self.movement in ("opening", "closing"):
            return super()._status_position_is_plausible(status_position)

        last_direction = getattr(self, "_last_completed_motion_direction", None)
        last_motion_time = getattr(self, "_last_completed_motion_monotonic", None)
        if (
            last_direction in ("opening", "closing")
            and last_motion_time is not None
            and self.position is not None
            and time.monotonic() - last_motion_time
            <= _STALE_STOP_DIRECTION_GUARD_SECONDS
        ):
            normalized = (
                0
                if status_position <= 5
                else 100
                if status_position >= 95
                else status_position
            )
            if last_direction == "closing":
                return normalized <= self.position
            return normalized >= self.position

        return super()._status_position_is_plausible(status_position)

    @property
    def parameter_write_schema_verified(self) -> bool:
        """Allow writes only for parameter layouts proven safe on live hardware."""
        if self._is_ps22027_verified_profile():
            return True
        if self._is_ps21050d_alias() or self._is_ps20040d_alias():
            return self.parameter_schema_verified
        return super().parameter_write_schema_verified

    async def async_pedestrian_open(self) -> None:
        """Run only the pedestrian command strategy verified for this controller."""
        strategy = self.pedestrian_strategy
        if strategy == PEDESTRIAN_STRATEGY_NONE:
            raise TmtCommandError(
                "No verified safe pedestrian command exists for this controller",
                translation_key="unsupported_controller",
            )

        if strategy == PEDESTRIAN_STRATEGY_RELAY4:
            # AutoProduct in TMT Chow 3.1.4 has a separate RELAY4 pedestrian
            # path. No controller is currently assigned to this strategy, so
            # this branch cannot run until an explicit verified mapping is
            # added. RELAY4 is sent once and requires its own ACK; there is no
            # motion-telemetry rescue and no automatic retry.
            await self._async_command("RELAY4", "ACK RELAY4")
            return

        if strategy == PEDESTRIAN_STRATEGY_PED_OPEN:
            await super().async_pedestrian_open()
            return

        raise TmtCommandError(
            "Unknown pedestrian command strategy",
            translation_key="unsupported_controller",
        )

    async def _async_set_ps22027_parameter(self, index: int, value: int) -> None:
        """Write one PS22027 field and verify the complete 20-slot frame."""
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
                    "Cannot write parameters before a valid PS22027 read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_ps22027_parameter_write(values)
            except PS22027ParameterError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            # Deliberately one write only. A timeout never resends WP,1.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # A successful write must return the complete frame we requested.
            # This catches any unexpected collateral change to the other 19 slots.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            if verified != values:
                raise TmtCommandError(
                    "PS22027 parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()

    async def async_set_parameter(self, index: int, value: int) -> None:
        """Write one parameter using the model-specific verified codec."""
        if self._is_ps22027_verified_profile():
            await self._async_set_ps22027_parameter(index, value)
            return

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
