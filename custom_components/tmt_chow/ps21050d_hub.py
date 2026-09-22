"""Controller alias support plus runtime gate-state hardening."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .const import ATTR_DEV_PARAM, SHADOW_REFRESH_SECONDS
from .controller_types import controller_capabilities, controller_family
from .hub import TmtChowHub as BaseTmtChowHub, TmtCommandError
from .mqtt import MqttError
from .parameter_codec import ParameterTransport, is_editable_parameter
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
from .ps19001_parameters import (
    APP_PARAMETERS as PS19001_PARAMETERS,
    CONTROLLER_TYPE as PS19001,
    PS19001ParameterError,
    encode_parameter_write as encode_ps19001_parameter_write,
    parse_parameter_response as parse_ps19001_parameter_response,
)
from .ps22027_parameters import (
    APP_PARAMETERS as PS22027_PARAMETERS,
    CONTROLLER_TYPE as PS22027,
    PS22027ParameterError,
    encode_parameter_write as encode_ps22027_parameter_write,
    parse_parameter_response as parse_ps22027_parameter_response,
)
from .ps22087b_parameters import (
    APP_MODEL as PS22087,
    CONTROLLER_TYPE as PS22087B,
    PARAMETERS as PS22087B_PARAMETERS,
    PS22087BParameterError,
    encode_parameter_write as encode_ps22087b_parameter_write,
    parse_parameter_response as parse_ps22087b_parameter_response,
    validate_requested_value as validate_ps22087b_requested_value,
)

_PS20005_APP_MODEL = "PS20005"
_PS20005A_CONTROLLER_TYPE = "PS20005A"
_PS20040_APP_MODEL = "PS20040"
_PS20040D_CONTROLLER_TYPE = "PS20040D"
_PS21050C_CONTROLLER_TYPE = "PS21050C"
_PS24118_CONFIGURED_TYPE = "PS24118"
_PS24118_LIVE_TYPE = "PS24118C"
_PS24118_APK_FAMILY_MODEL = "P190U"
_PS24118_STATUS_REFRESH_DELAYS = (
    0.0,
    0.5,
    0.75,
    1.25,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    8.0,
    10.0,
)
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

    PS21050C is another observed live identity for an account configured as
    PS21050. Real-hardware diagnostics prove that it returns the same exact
    20-slot RP,1 frame as the PS21050D profile, including an enabled pedestrian
    field. Reuse the codec and APK family/capabilities for this exact pair.
    Writes use a fresh full read, one WP,1 with no retry, and an exact full-frame
    readback before Home Assistant accepts the new value.

    PS24118 / PS24118C is an observed identity split for P190U hardware
    (DEV INFO: P190U,PS24118C,V02). Reuse only the P190U swing-family and
    pedestrian UI capability metadata; never borrow the P190U parameter codec.
    This controller's classic Shadow can remain stale after roughly three
    minutes of standby, while read-only WBT/MQTT RS is live and verified.
    Therefore RS is treated as the authoritative runtime state source for this
    exact identity and is refreshed after movement commands plus periodically.
    Movement commands are still sent exactly once and are never retried.

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

    def _is_ps21050c_alias(self) -> bool:
        return (
            self.controller_type == _PS21050C_CONTROLLER_TYPE
            and self.configured_controller_type == APP_MODEL
        )

    def _is_ps20040d_alias(self) -> bool:
        return (
            self.controller_type == _PS20040D_CONTROLLER_TYPE
            and self.configured_controller_type == _PS20040_APP_MODEL
        )

    def _is_ps24118_profile(self) -> bool:
        return (
            self.configured_controller_type == _PS24118_CONFIGURED_TYPE
            and self.controller_type in {
                _PS24118_CONFIGURED_TYPE,
                _PS24118_LIVE_TYPE,
            }
        )

    def _is_ps22027_verified_profile(self) -> bool:
        return (
            self.controller_type == PS22027
            and self.parameter_model_type == PS22027
            and self.parameter_model_source == "ps22027_wire20_verified"
        )

    def _is_ps22087b_alias(self) -> bool:
        return (
            self.configured_controller_type == PS22087
            and self.controller_type == PS22087B
            and self.parameter_model_type == PS22087B
            and self.parameter_model_source == "ps22087b_p710u_wire15_verified"
        )

    @property
    def pedestrian_strategy(self) -> str:
        """Return the currently permitted pedestrian command strategy."""
        if self._is_ps25007a_live_alias() and self._identified_source_tag() is not None:
            return PEDESTRIAN_STRATEGY_PED_OPEN
        return pedestrian_strategy_for(
            self.controller_type,
            self.controller_capabilities,
        )

    def _set_controller_type(self, controller_type: str | None) -> None:
        normalized = (controller_type or "").strip().upper()

        if (
            self.configured_controller_type == _PS24118_CONFIGURED_TYPE
            and normalized in {_PS24118_CONFIGURED_TYPE, _PS24118_LIVE_TYPE}
        ):
            # Diagnostics from real PS24118 hardware identify the board as
            # P190U,PS24118C,V02. Reuse only the APK family/UI capabilities.
            # Keep parameter_model_type unset so no P190U parameter writes can
            # ever be enabled through this identity alias.
            self.controller_type = normalized
            self.controller_family = controller_family(_PS24118_APK_FAMILY_MODEL)
            self.controller_capabilities = controller_capabilities(
                _PS24118_APK_FAMILY_MODEL
            )
            self.parameter_model_type = None
            self.parameter_model_source = "ps24118_p190u_capability_alias"
            self.model_parameter_schema = None
            return

        if normalized == PS22087 and self.configured_controller_type == PS22087:
            # The account model alone is not enough to select the P710U wire
            # layout. Wait for exact PS22087B live DEV INFO confirmation.
            self.controller_type = PS22087
            self.controller_family = controller_family(PS22087)
            self.controller_capabilities = controller_capabilities(PS22087)
            self.parameter_model_type = None
            self.parameter_model_source = "ps22087_waiting_for_ps22087b_live_identity"
            self.model_parameter_schema = None
            return

        if normalized == PS22087B and self.configured_controller_type == PS22087:
            self.controller_type = PS22087B
            self.controller_family = controller_family(PS22087)
            self.controller_capabilities = controller_capabilities(PS22087)
            self.parameter_model_type = PS22087B
            self.parameter_model_source = "ps22087b_p710u_wire15_verified"
            self.model_parameter_schema = PS22087B_PARAMETERS
            return

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

        if (
            normalized in {CONTROLLER_TYPE, _PS21050C_CONTROLLER_TYPE}
            and self.configured_controller_type == APP_MODEL
        ):
            self.controller_type = normalized
            self.controller_family = controller_family(APP_MODEL)
            self.controller_capabilities = controller_capabilities(APP_MODEL)
            self.parameter_model_type = CONTROLLER_TYPE
            self.parameter_model_source = (
                "apk_ps21050_alias"
                if normalized == CONTROLLER_TYPE
                else "apk_ps21050c_alias"
            )
            self.model_parameter_schema = APP_PARAMETERS
            return

        super()._set_controller_type(controller_type)

        if self.controller_type == PS19001 and self.parameter_model_type == PS19001:
            self.model_parameter_schema = PS19001_PARAMETERS
            self.parameter_model_source = "ps19001_wire19_verified"

        if normalized == _PS20005A_CONTROLLER_TYPE:
            # Exact capability alias only. Do not borrow a PS20005 parameter
            # schema and do not strip arbitrary model suffixes globally.
            self.controller_family = controller_family(_PS20005_APP_MODEL)
            self.controller_capabilities = controller_capabilities(_PS20005_APP_MODEL)
            return

        if self.controller_type == PS22027 and self.parameter_model_type == PS22027:
            self.model_parameter_schema = PS22027_PARAMETERS
            self.parameter_model_source = "ps22027_wire20_verified"

    def _apply_reported(self, reported: dict[str, Any]) -> None:
        """Keep stale PS24118 Shadow status from overriding live RS state."""
        if self._is_ps24118_profile():
            reported = {
                key: value
                for key, value in reported.items()
                if str(key).lower().replace("_", " ") != "dev status"
            }
        super()._apply_reported(reported)

    async def _async_ps24118_request_status(self) -> None:
        """Publish one read-only RS request without creating a command waiter."""
        if not self._is_ps24118_profile() or self.device_online is False:
            return
        try:
            await self._mqtt.async_publish(
                self.rx_topic,
                f"c=RS;src={self._source_tag}",
            )
        except MqttError:
            # A disconnect/race must not fail or resend a movement command.
            return

    async def _async_ps24118_status_monitor(self) -> None:
        """Refresh live state for the full motion window without resending motion."""
        task = asyncio.current_task()
        try:
            for delay in _PS24118_STATUS_REFRESH_DELAYS:
                if delay:
                    await asyncio.sleep(delay)
                if not self._is_ps24118_profile() or self._stopping:
                    return
                await self._async_ps24118_request_status()
        finally:
            if getattr(self, "_ps24118_status_task", None) is task:
                self._ps24118_status_task = None

    def _start_ps24118_status_monitor(self) -> None:
        if not self._is_ps24118_profile():
            return
        previous = getattr(self, "_ps24118_status_task", None)
        if previous is not None and not previous.done():
            previous.cancel()
        self._ps24118_status_task = asyncio.create_task(
            self._async_ps24118_status_monitor()
        )

    async def _shadow_refresh_loop(self) -> None:
        """Preserve Shadow metadata refresh and add PS24118 live RS polling."""
        while True:
            await asyncio.sleep(SHADOW_REFRESH_SECONDS)
            if not self._mqtt.connected:
                continue
            await self._async_request_shadow()
            if self._is_ps24118_profile():
                await self._async_ps24118_request_status()

    def _mqtt_state_changed(self, connected: bool) -> None:
        super()._mqtt_state_changed(connected)
        if connected and self._is_ps24118_profile():
            asyncio.create_task(self._async_ps24118_request_status())

    async def async_stop(self) -> None:
        task = getattr(self, "_ps24118_status_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._ps24118_status_task = None
        await super().async_stop()

    def _decode_parameter_response(self, payload: str) -> tuple[int, ...] | None:
        if self._is_ps22087b_alias():
            return parse_ps22087b_parameter_response(payload)
        if self.parameter_model_type == PS19001:
            return parse_ps19001_parameter_response(payload)
        if self._is_ps22027_verified_profile():
            return parse_ps22027_parameter_response(payload)
        return super()._decode_parameter_response(payload)

    def _parameter_transport(self) -> ParameterTransport:
        if self._is_ps22087b_alias():
            return ParameterTransport(1, "RP,1", "ACK RP,1", "ACK WP,1")
        return super()._parameter_transport()

    @property
    def parameter_schema_verified(self) -> bool:
        if self._is_ps22087b_alias():
            return True
        return super().parameter_schema_verified

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
        if self._is_ps22087b_alias():
            return True
        if (
            self._is_ps21050c_alias()
            or self._is_ps21050d_alias()
            or self._is_ps20040d_alias()
        ):
            return self.parameter_schema_verified
        return super().parameter_write_schema_verified

    async def async_open(self) -> None:
        if self._is_ps24118_profile():
            # Start read-only RS observation before the single movement publish.
            # If ACK FULL OPEN is lost after standby, fresh RS motion telemetry
            # can satisfy the base hub's no-ACK motion fallback without retrying.
            self._start_ps24118_status_monitor()
        await super().async_open()

    async def async_close(self) -> None:
        if self._is_ps24118_profile():
            self._start_ps24118_status_monitor()
        await super().async_close()

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
            if self._is_ps24118_profile():
                self._start_ps24118_status_monitor()
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

    async def _async_set_ps19001_parameter(self, index: int, value: int) -> None:
        """Write one PS19001 field and verify the complete 19-slot frame."""
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
                    "Cannot write parameters before a valid PS19001 read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_ps19001_parameter_write(values)
            except PS19001ParameterError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            # Never retry a parameter mutation automatically.
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            if verified != values:
                raise TmtCommandError(
                    "PS19001 parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()

    async def async_set_parameter(self, index: int, value: int) -> None:
        """Write one parameter using the model-specific verified codec."""
        if self._is_ps22087b_alias():
            await self._async_set_ps22087b_parameter(index, value)
            return
        if self.parameter_model_type == PS19001:
            await self._async_set_ps19001_parameter(index, value)
            return
        if self._is_ps22027_verified_profile():
            await self._async_set_ps22027_parameter(index, value)
            return

        if not (self._is_ps21050c_alias() or self._is_ps21050d_alias()):
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
                    "Cannot write parameters before a valid PS21050 read",
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

            # PS21050C write behavior has not previously been exercised through
            # Home Assistant, so require the complete 20-slot frame to match.
            # Keep the established PS21050D single-field readback rule unchanged.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = self._decode_parameter_response(verify_response)
            verification_failed = verified is None or (
                verified != values
                if self._is_ps21050c_alias()
                else verified[index] != int(value)
            )
            if verification_failed:
                raise TmtCommandError(
                    "PS21050 parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )

            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()

    async def _async_set_ps22087b_parameter(self, index: int, value: int) -> None:
        """Write one P710U field and verify the complete 15-slot frame."""
        try:
            validate_ps22087b_requested_value(index, value)
        except PS22087BParameterError as err:
            raise TmtCommandError(
                str(err), translation_key="unsupported_parameter_value"
            ) from err

        transport = self._parameter_transport()
        async with self._transaction_lock:
            current_response = await self._async_exchange(
                f"c={transport.read_command}", transport.read_ack
            )
            current = self._decode_parameter_response(current_response)
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid PS22087B read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_ps22087b_parameter_write(values)
            except PS22087BParameterError as err:
                raise TmtCommandError(
                    str(err), translation_key="unsupported_parameter_value"
                ) from err

            await self._async_exchange(
                f"c={command};src={self._source_tag}", transport.write_ack
            )
            verify_response = await self._async_exchange(
                f"c={transport.read_command}", transport.read_ack
            )
            verified = self._decode_parameter_response(verify_response)
            if verified != values:
                raise TmtCommandError(
                    "PS22087B parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )
            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()
