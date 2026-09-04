"""Runtime hub for one TMT Chow gate."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import json
import logging
import time
from typing import Any

from .const import (
    ATTR_DEV_INFO,
    ATTR_DEV_PARAM,
    ATTR_DEV_STATUS,
    ATTR_LAST_RESPONSE,
    ATTR_LOCAL_IP,
    ATTR_UART_VERSION,
    ATTR_WBT_VERSION,
    ATTR_WIFI_SSID,
    COMMAND_TIMEOUT,
    MQTT_AVAILABILITY_GRACE_SECONDS,
    PARAMETER_BOOTSTRAP_RETRY_SECONDS,
    PARAMETER_REFRESH_SECONDS,
    SHADOW_REFRESH_SECONDS,
)
from .controller_types import (
    controller_capabilities,
    controller_family,
    normalize_controller_type,
)
from .model_parameter_schemas import parameter_schema_for
from .mqtt import AsyncMqttClient, MqttError
from .parameter_codec import (
    ParameterCodecError,
    decode_model_parameter_response,
    encode_model_parameter_write,
    is_editable_parameter,
    parameter_transport_for,
)
from .protocol import (
    GateStatus,
    decode_dev_status,
    extract_shadow_reported,
    parse_ack_rs,
    parse_position,
)

_LOGGER = logging.getLogger(__name__)


class TmtCommandError(Exception):
    """A command was rejected, timed out, or could not be sent."""

    def __init__(
        self,
        message: str,
        *,
        translation_key: str = "command_failed",
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders or {}


class TmtChowHub:
    """Own MQTT state, gate commands, and parameter transactions."""

    def __init__(
        self,
        *,
        uuid: str,
        thing_name: str,
        name: str,
        endpoint: str,
        certificate_pem: str,
        private_key: str,
        source_tag: str,
        product_type: str,
        device_type: str = "",
    ) -> None:
        self.uuid = uuid
        self.thing_name = thing_name
        self.name = name
        self.product_type = product_type
        initial_controller_type = normalize_controller_type(device_type)
        self.controller_type: str | None = None
        self.controller_family: str | None = None
        self.controller_capabilities: frozenset[str] = frozenset()
        self.model_parameter_schema: tuple | None = None
        self._set_controller_type(initial_controller_type or None)
        self.position: int | None = None
        self.battery_percent: int | None = None
        self.movement: str | None = None
        self.is_operating: bool | None = None
        self.parameters: tuple[int, ...] | None = None
        self.device_online: bool | None = None
        self.attributes: dict[str, Any] = {}
        self._source_tag = source_tag
        self._listeners: set[Callable[[], None]] = set()
        self._waiters: list[tuple[str, asyncio.Future[str]]] = []
        self._transaction_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._shadow_refresh_task: asyncio.Task[None] | None = None
        self._availability_expiry_task: asyncio.Task[None] | None = None
        self._last_message_monotonic: float | None = None
        self._last_shadow_monotonic: float | None = None
        self._last_live_position_monotonic: float | None = None
        self._last_operating_status_monotonic: float | None = None
        self._state_synchronized = False
        self._stopping = False

        # TMT uses the device UUID as the topic/Shadow thing identifier.
        self.rx_topic = f"{uuid}/wbt01Rx"
        self.tx_topic = f"{uuid}/wbt01Tx"
        self.position_topic = f"{uuid}/position"
        self.shadow_get_topic = f"$aws/things/{uuid}/shadow/get"
        self.shadow_get_accepted_topic = f"{self.shadow_get_topic}/accepted"
        self.shadow_documents_topic = f"$aws/things/{uuid}/shadow/update/documents"
        self._mqtt = AsyncMqttClient(
            endpoint=endpoint,
            client_id=f"ha-{uuid}",
            certificate_pem=certificate_pem,
            private_key=private_key,
            topics=(
                self.tx_topic,
                self.position_topic,
                self.shadow_get_accepted_topic,
                self.shadow_documents_topic,
            ),
            message_callback=self._async_message,
            state_callback=self._mqtt_state_changed,
        )

    @property
    def available(self) -> bool:
        if self.device_online is False:
            return False
        if self._mqtt.connected and self._state_synchronized:
            return True
        return (
            self._last_shadow_monotonic is not None
            and time.monotonic() - self._last_shadow_monotonic
            < MQTT_AVAILABILITY_GRACE_SECONDS
        )

    @property
    def mqtt_connected(self) -> bool:
        return self._mqtt.connected

    @property
    def parameter_schema_verified(self) -> bool:
        """Return whether the APK supplies both schema and wire codec."""
        return (
            self.model_parameter_schema is not None
            and parameter_transport_for(self.controller_type) is not None
        )

    @property
    def supports_parameters(self) -> bool:
        """Return whether this concrete controller has a decoded vendor schema."""
        return self.parameter_schema_verified

    @property
    def may_probe_parameters(self) -> bool:
        """Return whether this model has a safe vendor-specific read codec."""
        return self.parameter_schema_verified

    async def async_start(self) -> None:
        self._stopping = False
        await self._mqtt.async_start()
        if self.may_probe_parameters:
            try:
                await self.async_refresh_parameters()
            except TmtCommandError as err:
                _LOGGER.warning("Initial TMT parameter read failed: %s", err)
            self._refresh_task = asyncio.create_task(self._parameter_refresh_loop())
        self._shadow_refresh_task = asyncio.create_task(self._shadow_refresh_loop())

    async def async_stop(self) -> None:
        self._stopping = True
        if self._refresh_task:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None
        if self._shadow_refresh_task:
            self._shadow_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._shadow_refresh_task
            self._shadow_refresh_task = None
        if self._availability_expiry_task:
            self._availability_expiry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._availability_expiry_task
            self._availability_expiry_task = None
        for _, future in self._waiters:
            if not future.done():
                future.cancel()
        self._waiters.clear()
        await self._mqtt.async_stop()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _set_controller_type(self, controller_type: str | None) -> None:
        """Apply all model metadata from one concrete controller type."""
        normalized = normalize_controller_type(controller_type)
        self.controller_type = normalized or None
        self.controller_family = controller_family(self.controller_type)
        self.controller_capabilities = controller_capabilities(self.controller_type)
        self.model_parameter_schema = parameter_schema_for(self.controller_type)

    def _parameter_transport(self):
        transport = parameter_transport_for(self.controller_type)
        if transport is None or self.model_parameter_schema is None:
            raise TmtCommandError(
                "No verified parameter codec exists for this controller",
                translation_key="unsupported_controller",
            )
        return transport

    async def async_open(self) -> None:
        acknowledged = await self._async_command(
            "FULL OPEN",
            "ACK FULL OPEN",
            motion_direction="opening",
        )
        if acknowledged:
            self.is_operating = True
            self.movement = "opening"
            self._notify()

    async def async_close(self) -> None:
        acknowledged = await self._async_command(
            "FULL CLOSE",
            "ACK FULL CLOSE",
            motion_direction="closing",
        )
        if acknowledged:
            self.is_operating = True
            self.movement = "closing"
            self._notify()

    async def async_pedestrian_open(self) -> None:
        """Open to the controller's configured pedestrian/partial position."""
        acknowledged = await self._async_command(
            "PED OPEN",
            "ACK PED OPEN",
            motion_direction="opening",
        )
        if acknowledged:
            self.is_operating = True
            self.movement = "opening"
            self._notify()

    async def async_stop_gate(self) -> None:
        await self._async_command("STOP", "ACK STOP")
        self.is_operating = False
        self.movement = None
        self._notify()

    async def async_refresh_parameters(self) -> None:
        transport = self._parameter_transport()
        async with self._transaction_lock:
            response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            parsed = decode_model_parameter_response(
                self.controller_type,
                response,
            )
            if parsed is None:
                raise TmtCommandError(
                    "The gate returned no valid model-specific parameter set",
                    translation_key="invalid_parameter_set",
                )
            self.parameters = parsed
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, parsed))
            self._notify()

    async def async_set_parameter(self, index: int, value: int) -> None:
        transport = self._parameter_transport()
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

        async with self._transaction_lock:
            current_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            current = decode_model_parameter_response(
                self.controller_type,
                current_response,
            )
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid model-specific read",
                    translation_key="parameters_not_ready",
                )

            updated = list(current)
            updated[index] = int(value)
            values = tuple(updated)
            try:
                command = encode_model_parameter_write(
                    self.controller_type,
                    values,
                )
            except ParameterCodecError as err:
                raise TmtCommandError(
                    str(err),
                    translation_key="unsupported_parameter_value",
                ) from err

            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                transport.write_ack,
            )

            # Always read back after a write. This is deliberately stricter than
            # the vendor UI and prevents a model-specific packing mismatch from
            # being accepted silently.
            verify_response = await self._async_exchange(
                f"c={transport.read_command}",
                transport.read_ack,
            )
            verified = decode_model_parameter_response(
                self.controller_type,
                verify_response,
            )
            if verified is None or verified[index] != int(value):
                raise TmtCommandError(
                    "Parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )
            self.parameters = verified
            self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, verified))
            self._notify()

    async def _async_command(
        self,
        command: str,
        acknowledgement: str,
        *,
        motion_direction: str | None = None,
    ) -> bool:
        """Send one command and return whether its explicit ACK was received.

        Movement commands are never resent. If the explicit ACK is lost but
        fresh post-command telemetry proves that the requested motion started,
        the command is accepted as successful and False is returned so callers
        do not overwrite newer live state with optimistic state.
        """
        async with self._transaction_lock:
            start_position = self.position
            start_operating = self.is_operating
            command_started = time.monotonic()
            try:
                await self._async_exchange(
                    f"c={command};src={self._source_tag}",
                    acknowledgement,
                )
                return True
            except TmtCommandError as err:
                if (
                    err.translation_key == "no_acknowledgement"
                    and isinstance(err.__cause__, TimeoutError)
                    and motion_direction is not None
                    and self._motion_confirms_command(
                        motion_direction,
                        start_position=start_position,
                        start_operating=start_operating,
                        command_started=command_started,
                    )
                ):
                    _LOGGER.warning(
                        "%s was not received for %s, but fresh gate telemetry "
                        "confirms %s motion; treating the command as successful",
                        acknowledgement,
                        command,
                        motion_direction,
                    )
                    return False
                raise

    def _motion_confirms_command(
        self,
        direction: str,
        *,
        start_position: int | None,
        start_operating: bool | None,
        command_started: float,
    ) -> bool:
        """Return whether fresh telemetry proves a timed-out motion command ran."""
        if start_operating is True:
            return False

        fresh_operating_status = (
            self._last_operating_status_monotonic is not None
            and self._last_operating_status_monotonic >= command_started
        )
        if (
            fresh_operating_status
            and self.is_operating is True
            and self.movement == direction
        ):
            return True

        fresh_live_position = (
            self._last_live_position_monotonic is not None
            and self._last_live_position_monotonic >= command_started
        )
        if (
            not fresh_live_position
            or start_position is None
            or self.position is None
        ):
            return False
        if direction == "opening":
            return self.position > start_position
        if direction == "closing":
            return self.position < start_position
        return False

    async def _async_exchange(self, payload: str, expected: str) -> str:
        if not self._mqtt.connected or self.device_online is False:
            raise TmtCommandError(
                "The gate is offline",
                translation_key="gate_offline",
            )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        waiter = (expected, future)
        self._waiters.append(waiter)
        try:
            # Deliberately one publish only. A timeout never causes command retry.
            await self._mqtt.async_publish(self.rx_topic, payload)
            return await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
        except (MqttError, TimeoutError) as err:
            raise TmtCommandError(
                f"No {expected} acknowledgement",
                translation_key="no_acknowledgement",
                translation_placeholders={"acknowledgement": expected},
            ) from err
        finally:
            with contextlib.suppress(ValueError):
                self._waiters.remove(waiter)

    async def _async_refresh_parameters_safely(self) -> None:
        try:
            await self.async_refresh_parameters()
        except TmtCommandError as err:
            _LOGGER.debug("Model-specific parameter bootstrap failed: %s", err)

    async def _parameter_refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(
                PARAMETER_REFRESH_SECONDS
                if self.parameters is not None
                else PARAMETER_BOOTSTRAP_RETRY_SECONDS
            )
            if not self.available or not self.may_probe_parameters:
                continue
            try:
                await self.async_refresh_parameters()
            except TmtCommandError as err:
                _LOGGER.debug("Periodic parameter read failed: %s", err)

    async def _shadow_refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(SHADOW_REFRESH_SECONDS)
            if self._mqtt.connected:
                await self._async_request_shadow()

    async def _async_message(self, topic: str, payload: str) -> None:
        self._last_message_monotonic = time.monotonic()
        if topic == self.tx_topic:
            self.attributes[ATTR_LAST_RESPONSE] = payload
            parsed_parameters = decode_model_parameter_response(
                self.controller_type,
                payload,
            )
            if parsed_parameters is not None:
                self.parameters = parsed_parameters
                self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, parsed_parameters))
            status = parse_ack_rs(payload)
            if status is not None:
                self._apply_status(status)
            if "NAK" in payload:
                for _, future in tuple(self._waiters):
                    if not future.done():
                        future.set_exception(
                            TmtCommandError(
                                payload,
                                translation_key="command_rejected",
                                translation_placeholders={"response": payload},
                            )
                        )
            else:
                for expected, future in tuple(self._waiters):
                    if expected in payload and not future.done():
                        future.set_result(payload)
        elif topic == self.position_topic:
            position = parse_position(payload)
            if position is not None:
                self._last_live_position_monotonic = time.monotonic()
                self._apply_position(position)
        elif topic in (self.shadow_get_accepted_topic, self.shadow_documents_topic):
            try:
                document = json.loads(payload)
            except (TypeError, ValueError):
                document = {}
            reported = extract_shadow_reported(document)
            if reported:
                self._apply_reported(reported)
        self._notify()

    def _apply_reported(self, reported: dict[str, Any]) -> None:
        self._state_synchronized = True
        self._last_shadow_monotonic = time.monotonic()
        normalized = {
            str(key).lower().replace("_", " "): value
            for key, value in reported.items()
        }
        connected = normalized.get("connected")
        if isinstance(connected, bool):
            self.device_online = connected
        elif isinstance(connected, str):
            self.device_online = connected.lower() == "true"

        mapping = {
            "dev status": ATTR_DEV_STATUS,
            "dev info": ATTR_DEV_INFO,
            "dev param": ATTR_DEV_PARAM,
            "uart ver": ATTR_UART_VERSION,
            "wbt ver": ATTR_WBT_VERSION,
            "ip": ATTR_LOCAL_IP,
            "wifi ssid": ATTR_WIFI_SSID,
        }
        for key, attribute in mapping.items():
            if key in normalized:
                self.attributes[attribute] = normalized[key]
        status_payload = normalized.get("dev status")
        if isinstance(status_payload, str):
            self._apply_status(decode_dev_status(status_payload))
        device_info = normalized.get("dev info")
        if isinstance(device_info, str):
            fields = [field.strip().upper() for field in device_info.split(",")]
            if len(fields) >= 2:
                previous = self.controller_type
                self._set_controller_type(fields[1])
                if (
                    previous != self.controller_type
                    and self.may_probe_parameters
                    and self._refresh_task is None
                    and not self._stopping
                ):
                    self._refresh_task = asyncio.create_task(
                        self._parameter_refresh_loop()
                    )
                    asyncio.create_task(self._async_refresh_parameters_safely())
        parameter_payload = normalized.get("dev param")
        if isinstance(parameter_payload, str):
            parsed = decode_model_parameter_response(
                self.controller_type,
                parameter_payload,
            )
            if parsed is not None:
                self.parameters = parsed

    def _apply_status(self, status: GateStatus) -> None:
        if status.is_operating is not None:
            self.is_operating = status.is_operating

        if status.is_operating:
            self._last_operating_status_monotonic = time.monotonic()
            # The vendor app uses bit 7 of status byte 3 as the movement side
            # while byte 2 bit 6 says that the motor is operating. The low
            # position bits in Shadow can be stale during travel; live movement
            # percentages arrive on the dedicated /position topic.
            if status.is_open_direction is not None:
                self.movement = "opening" if status.is_open_direction else "closing"
        else:
            if status.position is not None and self._status_position_is_plausible(
                status.position
            ):
                self._apply_position(status.position, derive_movement=False)
            self.movement = None
        if status.battery_percent is not None:
            self.battery_percent = status.battery_percent

    def _status_position_is_plausible(self, status_position: int) -> bool:
        """Reject a stale stop-position that contradicts the completed motion."""
        if self.movement is None or self.position is None:
            return True
        normalized = (
            0
            if status_position <= 5
            else 100
            if status_position >= 95
            else status_position
        )
        if self.movement == "closing":
            return normalized <= self.position
        if self.movement == "opening":
            return normalized >= self.position
        return True

    def _apply_position(self, position: int, *, derive_movement: bool = True) -> None:
        old_position = self.position
        normalized = 0 if position <= 5 else 100 if position >= 95 else position
        self.position = normalized

        if derive_movement and self.is_operating is not False and old_position is not None:
            if normalized > old_position:
                self.movement = "opening"
            elif normalized < old_position:
                self.movement = "closing"

        reached_closed = normalized == 0 and self.movement != "opening"
        reached_open = normalized == 100 and self.movement != "closing"
        if reached_closed or reached_open:
            self.is_operating = False
            self.movement = None

    def _mqtt_state_changed(self, connected: bool) -> None:
        if connected:
            self._state_synchronized = False
            if self._availability_expiry_task:
                self._availability_expiry_task.cancel()
                self._availability_expiry_task = None
            asyncio.create_task(self._async_request_shadow())
        else:
            for _, future in tuple(self._waiters):
                if not future.done():
                    future.set_exception(
                        TmtCommandError(
                            "MQTT disconnected",
                            translation_key="mqtt_disconnected",
                        )
                    )
            if not self._stopping:
                if self._availability_expiry_task:
                    self._availability_expiry_task.cancel()
                self._availability_expiry_task = asyncio.create_task(
                    self._expire_availability_after_grace()
                )
        self._notify()

    async def _expire_availability_after_grace(self) -> None:
        task = asyncio.current_task()
        try:
            await asyncio.sleep(MQTT_AVAILABILITY_GRACE_SECONDS)
            self._notify()
        finally:
            if self._availability_expiry_task is task:
                self._availability_expiry_task = None

    async def _async_request_shadow(self) -> None:
        try:
            await self._mqtt.async_publish(self.shadow_get_topic, "{}")
        except MqttError:
            return

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - HA listener failure must not drop MQTT
                _LOGGER.exception("TMT Chow state listener failed")
