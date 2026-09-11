"""PS21050D alias support plus runtime gate-state hardening."""

from __future__ import annotations

import time

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

_STALE_STOP_DIRECTION_GUARD_SECONDS = 30.0
_PS22027 = "PS22027"
_PS22027_PARAMETER_COUNT = 20
_PS22027_DUPLICATE_PREFIX = (
    "func_open_over_current",
    "func_close_over_current",
    "func_slide_gate_operation_mode",
    "func_open_over_current",
    "func_close_over_current",
)


def _parse_ps22027_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse the PS22027's observed 20-value RP,1 frame without reinterpreting it.

    The APK-derived model matrix currently contains two inherited P190 current
    entries before the PS22027-specific fields, producing 22 logical entries.
    Live PS22027 diagnostics show a 20-value DEV PARAM frame. Keep this test
    path deliberately read-only and preserve the raw controller values until
    the exact write encoding has been verified on hardware.
    """
    if not isinstance(payload, str):
        return None

    clean = payload.split(";", 1)[0].strip()
    body: str | None = None
    for prefix in ("ACK RP,1", "ACK RP"):
        if not clean.startswith(prefix):
            continue
        tail = clean[len(prefix) :]
        if tail[:1] not in {":", ","}:
            return None
        body = tail[1:]
        break

    if body is None:
        if clean.startswith("ACK "):
            return None
        body = clean.lstrip(":")

    tokens = body.split(",") if body else []
    if len(tokens) != _PS22027_PARAMETER_COUNT:
        return None
    try:
        return tuple(int(token.strip()) for token in tokens)
    except ValueError:
        return None


class TmtChowHub(BaseTmtChowHub):
    """Runtime hub with model exceptions and stale-stop protection.

    TMT Chow 3.1.4 contains a PS21050 product implementation but no separate
    PS21050D implementation. The account API identifies this controller as
    PS21050, while live DEV INFO reports PS21050D. Preserve the concrete live
    identity but use the app's family/capability metadata and exact 20-value
    RP,1/WP,1 parameter layout for this alias pair.

    PS22027 currently needs a separate read-only compatibility path. The
    generated APK schema contains two inherited P190 current entries in front
    of the 20 PS22027-specific entries, while live diagnostics expose a
    20-value frame. The test path removes only that duplicate prefix and never
    enables parameter writes.

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

    def _is_ps22027_read_only_profile(self) -> bool:
        return (
            self.controller_type == _PS22027
            and self.parameter_model_type == _PS22027
            and self.parameter_model_source == "ps22027_wire20_read_only"
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

        if (
            self.controller_type == _PS22027
            and self.parameter_model_type == _PS22027
            and self.model_parameter_schema is not None
            and len(self.model_parameter_schema) == _PS22027_PARAMETER_COUNT + 2
            and tuple(spec[1] for spec in self.model_parameter_schema[:5])
            == _PS22027_DUPLICATE_PREFIX
        ):
            self.model_parameter_schema = self.model_parameter_schema[2:]
            self.parameter_model_source = "ps22027_wire20_read_only"

    def _decode_parameter_response(self, payload: str) -> tuple[int, ...] | None:
        if self._is_ps22027_read_only_profile():
            return _parse_ps22027_parameter_response(payload)
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
        if self._is_ps22027_read_only_profile():
            return False
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
