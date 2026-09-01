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
    has_verified_parameter_schema,
    normalize_controller_type,
)
from .model_parameter_schemas import parameter_schema_for
from .model_parameters import (
    get_model_parameter_count,
    get_model_parameter_schema,
    get_model_parameter_schema_id,
)
from .mqtt import AsyncMqttClient, MqttError
from .parameters import PARAMETERS, encode_parameter_write, parse_parameter_response
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
        self.controller_type: str | None = initial_controller_type or None
        self.controller_family: str | None = controller_family(self.controller_type)
        self.controller_capabilities: frozenset[str] = controller_capabilities(
            self.controller_type
        )
        self.model_parameter_schema: tuple[dict, ...] = get_model_parameter_schema(
            self.controller_type
        )
        self.model_parameter_schema_id: str | None = get_model_parameter_schema_id(
            self.controller_type
        )
        self.model_parameter_count: int = get_model_parameter_count(
            self.controller_type
        )
        self.model_parameter_schema = parameter_schema_for(self.controller_type)
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
        """Return whether the 17-value parameter schema is verified."""
        return has_verified_parameter_schema(self.controller_type)

    @property
    def supports_parameters(self) -> bool:
        """Return whether the verified parameter selectors may be used.

        Older config entries can briefly lack device_type until DEV INFO arrives,
        so a strictly parsed 17-value response remains a temporary compatibility
        fallback only while the controller type is still unknown.
        """
        return self.parameter_schema_verified or (
            self.controller_type is None and self.parameters is not None
        )

    @property
    def may_probe_parameters(self) -> bool:
        """Return whether it is safe to probe the verified RP,1 schema."""
        return self.parameter_schema_verified or self.controller_type is None

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

    async def async_open(self) -> None:
        await self._async_command("FULL OPEN", "ACK FULL OPEN")
        self.is_operating = True
        self.movement = "opening"
        self._notify()

    async def async_close(self) -> None:
        await self._async_command("FULL CLOSE", "ACK FULL CLOSE")
        self.is_operating = True
        self.movement = "closing"
        self._notify()

    async def async_stop_gate(self) -> None:
        await self._async_command("STOP", "ACK STOP")
        self.is_operating = False
        self.movement = None
        self._notify()

    async def async_refresh_parameters(self) -> None:
        async with self._transaction_lock:
            response = await self._async_exchange("c=RP,1", "ACK RP,1")
            parsed = parse_parameter_response(response)
            if parsed is None:
                raise TmtCommandError(
                    "The gate returned no valid parameter set",
                    translation_key="invalid_parameter_set",
                )
            self.parameters = parsed
            self._notify()

    async def async_set_parameter(self, index: int, value: int) -> None:
        if not self.supports_parameters:
            raise TmtCommandError(
                "The controller is not a verified PS21053/PS21053C",
                translation_key="unsupported_controller",
            )
        if not 0 <= index < len(PARAMETERS):
            raise TmtCommandError(
                "Unknown gate parameter",
                translation_key="unknown_parameter",
            )
        async with self._transaction_lock:
            current_response = await self._async_exchange("c=RP,1", "ACK RP,1")
            current = parse_parameter_response(current_response)
            if current is None:
                raise TmtCommandError(
                    "Cannot write parameters before a valid read",
                    translation_key="parameters_not_ready",
                )
            self.parameters = current
            updated = list(current)
            updated[index] = value
            values = tuple(updated)
            command = encode_parameter_write(values)
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                "ACK WP,1",
            )
            verify_response = await self._async_exchange("c=RP,1", "ACK RP,1")
            verified = parse_parameter_response(verify_response)
            if verified != values:
                raise TmtCommandError(
                    "Parameter verification failed after write",
                    translation_key="parameter_verification_failed",
                )
            self.parameters = verified
            self._notify()

    async def _async_command(self, command: str, acknowledgement: str) -> None:
        async with self._transaction_lock:
            await self._async_exchange(
                f"c={command};src={self._source_tag}",
                acknowledgement,
            )

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
            parsed_parameters = parse_parameter_response(payload)
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
                self.controller_type = normalize_controller_type(fields[1]) or None
                self.controller_family = controller_family(self.controller_type)
                self.controller_capabilities = controller_capabilities(
                    self.controller_type
                )
                self.model_parameter_schema = get_model_parameter_schema(
                    self.controller_type
                )
                self.model_parameter_schema_id = get_model_parameter_schema_id(
                    self.controller_type
                )
                self.model_parameter_count = get_model_parameter_count(
                    self.controller_type
                )
                self.model_parameter_schema = parameter_schema_for(
                    self.controller_type
                )
        parameter_payload = normalized.get("dev param")
        if isinstance(parameter_payload, str):
            candidate = "ACK RP,1:" + parameter_payload.lstrip(":")
            parsed = parse_parameter_response(candidate)
            if parsed is not None:
                self.parameters = parsed

    def _apply_status(self, status: GateStatus) -> None:
        if status.is_operating is not None:
            self.is_operating = status.is_operating

        if status.is_operating:
            # The vendor app uses bit 7 of status byte 3 as the movement side
            # while byte 2 bit 6 says that the motor is operating. The low
            # position bits in Shadow can be stale during travel; live movement
            # percentages arrive on the dedicated /position topic.
            if status.is_open_direction is not None:
                self.movement = "opening" if status.is_open_direction else "closing"
        else:
            if status.position is not None:
                self._apply_position(status.position, derive_movement=False)
            self.movement = None
        if status.battery_percent is not None:
            self.battery_percent = status.battery_percent

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
