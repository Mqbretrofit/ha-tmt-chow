"""Runtime hub for one TMT Chow gate."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import hashlib
import json
import logging
import re
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
from .mqtt import AsyncMqttClient, MqttError
from .parameters import (
    PARAMETERS,
    P710U_FUNCTIONS,
    encode_parameter_write,
    encode_write_function,
    parse_parameter_response,
    parse_read_function_response,
)
from .protocol import (
    GateStatus,
    decode_dev_status,
    extract_shadow_reported,
    parse_ack_rs,
    parse_position,
)

_LOGGER = logging.getLogger(__name__)
_READABLE_CONTROLLERS = {"PS21053", "PS21053C", "PS22087B"}
_WRITABLE_CONTROLLERS = {"PS21053", "PS21053C"}
_NO_BATTERY_CONTROLLERS = {"PS22087B"}


def _diag_text(payload: str) -> str:
    """Return a useful, privacy-safe MQTT payload preview."""
    text = payload.replace("\r", "\\r").replace("\n", "\\n")
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "<redacted-email>",
        text,
    )
    text = re.sub(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "<redacted-ip>",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b",
        "<redacted-mac>",
        text,
    )
    if len(text) > 700:
        return text[:700] + f"... <truncated {len(text) - 700} chars>"
    return text


def _diag_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]


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
        self.device_type = device_type
        self.controller_type: str | None = None
        self.proposal_code: str | None = None
        self.function_values: dict[str, int] = {}
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
        self._identity_event = asyncio.Event()
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
    def model_name(self) -> str:
        """Return the best controller model name currently known."""
        controller = self.controller_type or self.device_type
        if controller and self.product_type:
            return f"{controller} (product {self.product_type})"
        return controller or self.product_type or "Chow gate controller"

    @property
    def supports_battery(self) -> bool:
        """Whether this controller exposes a meaningful battery percentage."""
        controller = self.controller_type or self.device_type
        return controller not in _NO_BATTERY_CONTROLLERS

    @property
    def supports_parameters(self) -> bool:
        # A parsed RP,1 response is authoritative for read/state sync.
        # DEV INFO can arrive later than RP,1 after an MQTT reconnect.
        return (
            self.controller_type in _READABLE_CONTROLLERS
            or self.parameters is not None
        )

    @property
    def supports_parameter_writes(self) -> bool:
        """Return whether this controller has a verified writable profile."""
        return (
            self.controller_type in _WRITABLE_CONTROLLERS
            and self.parameters is not None
            and len(self.parameters) == len(PARAMETERS)
        )

    async def async_start(self) -> None:
        self._stopping = False
        _LOGGER.warning(
            "TMTDIAG HUB_START product_type=%s rx_topic=%s tx_topic=%s "
            "position_topic=%s shadow_get_topic=%s",
            self.product_type,
            self.rx_topic,
            self.tx_topic,
            self.position_topic,
            self.shadow_get_topic,
        )
        await self._mqtt.async_start()
        _LOGGER.warning(
            "TMTDIAG HUB_MQTT_READY connected=%s device_online=%s state_synchronized=%s",
            self._mqtt.connected,
            self.device_online,
            self._state_synchronized,
        )
        try:
            await self.async_refresh_parameters()
        except TmtCommandError as err:
            _LOGGER.warning("Initial TMT parameter read failed: %s", err)

        # DEV INFO normally arrives from Shadow while the first RP,1 read is
        # in flight. Wait briefly so UART-v2 P710U controllers can immediately
        # switch to their official READ FUNCTION parameter protocol.
        if self.controller_type is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._identity_event.wait(), timeout=3)

        if self.controller_type == "PS22087B":
            try:
                await self.async_refresh_functions()
            except TmtCommandError as err:
                _LOGGER.warning("Initial P710U READ FUNCTION failed: %s", err)

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
            _LOGGER.warning(
                "TMTDIAG PARAM_READ_START controller_type=%r supports_parameters=%s "
                "device_online=%s mqtt_connected=%s",
                self.controller_type,
                self.supports_parameters,
                self.device_online,
                self._mqtt.connected,
            )
            response = await self._async_exchange("c=RP,1", "ACK RP,1")
            parsed = parse_parameter_response(response)
            _LOGGER.warning(
                "TMTDIAG PARAM_READ_RESPONSE len=%s sha256=%s parsed=%s payload=%s",
                len(response),
                _diag_hash(response),
                parsed is not None,
                _diag_text(response),
            )
            if parsed is None:
                raise TmtCommandError(
                    "The gate returned no valid parameter set",
                    translation_key="invalid_parameter_set",
                )
            self.parameters = parsed
            _LOGGER.warning(
                "TMTDIAG RUNTIME_READY controller_type=%r device_type=%r "
                "product_type=%s parameter_count=%s available=%s "
                "battery_supported=%s",
                self.controller_type,
                self.device_type,
                self.product_type,
                len(parsed),
                self.available,
                self.supports_battery,
            )
            self._notify()

    async def async_refresh_functions(self) -> None:
        """Read the official UART-v2 P710U function set."""
        async with self._transaction_lock:
            response = await self._async_exchange(
                "c=READ FUNCTION",
                "ACK READ FUNCTION",
            )
            parsed = parse_read_function_response(response)
            _LOGGER.warning(
                "TMTDIAG P710U_FUNCTION_READ parsed=%s count=%s keys=%s payload=%s",
                parsed is not None,
                len(parsed or {}),
                list((parsed or {}).keys()),
                _diag_text(response),
            )
            if parsed is None:
                raise TmtCommandError(
                    "The controller returned no valid READ FUNCTION set",
                    translation_key="invalid_parameter_set",
                )
            self.function_values = parsed
            self._notify()

    async def async_set_function(self, key: str, value: int) -> None:
        """Write one P710U function by sending the complete preserved set."""
        if self.controller_type != "PS22087B":
            raise TmtCommandError(
                "The controller does not use the P710U function protocol",
                translation_key="unsupported_controller",
            )
        key = key.upper()
        if key not in self.function_values:
            raise TmtCommandError(
                "Unknown P710U function",
                translation_key="unknown_parameter",
            )

        definition = P710U_FUNCTIONS.get(key)
        if definition is None or value not in definition[1]:
            raise TmtCommandError(
                "Unsupported P710U function value",
                translation_key="unsupported_parameter_value",
            )

        async with self._transaction_lock:
            current_response = await self._async_exchange(
                "c=READ FUNCTION",
                "ACK READ FUNCTION",
            )
            current = parse_read_function_response(current_response)
            if current is None or key not in current:
                raise TmtCommandError(
                    "Cannot write before a valid READ FUNCTION",
                    translation_key="parameters_not_ready",
                )

            updated = dict(current)
            updated[key] = value
            command = encode_write_function(updated)
            _LOGGER.warning(
                "TMTDIAG P710U_FUNCTION_WRITE key=%s old=%s new=%s count=%s",
                key,
                current.get(key),
                value,
                len(updated),
            )

            # The official UART-v2 protocol writes the complete function set.
            # Do not guess an ACK token: publish once, then verify with a fresh
            # READ FUNCTION. A rejected/ignored write is caught by verification.
            await self._mqtt.async_publish(
                self.rx_topic,
                f"c={command};src={self._source_tag}",
            )
            await asyncio.sleep(1.0)

            verify_response = await self._async_exchange(
                "c=READ FUNCTION",
                "ACK READ FUNCTION",
            )
            verified = parse_read_function_response(verify_response)
            if verified is None or verified.get(key) != value:
                raise TmtCommandError(
                    "P710U function verification failed after write",
                    translation_key="parameter_verification_failed",
                )
            self.function_values = verified
            self._notify()

    async def async_set_parameter(self, index: int, value: int) -> None:
        if not self.supports_parameter_writes:
            raise TmtCommandError(
                "The controller does not have a verified writable parameter profile",
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
        _LOGGER.warning(
            "TMTDIAG MQTT_EXCHANGE_START expected=%r mqtt_connected=%s "
            "device_online=%s topic=%s payload_len=%s payload_sha256=%s payload=%s",
            expected,
            self._mqtt.connected,
            self.device_online,
            self.rx_topic,
            len(payload),
            _diag_hash(payload),
            _diag_text(payload),
        )
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
            _LOGGER.warning(
                "TMTDIAG MQTT_EXCHANGE_PUBLISHED expected=%r waiter_count=%s",
                expected,
                len(self._waiters),
            )
            response = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            _LOGGER.warning(
                "TMTDIAG MQTT_EXCHANGE_ACK expected=%r response_len=%s "
                "response_sha256=%s response=%s",
                expected,
                len(response),
                _diag_hash(response),
                _diag_text(response),
            )
            return response
        except (MqttError, TimeoutError) as err:
            _LOGGER.warning(
                "TMTDIAG MQTT_EXCHANGE_FAILURE expected=%r error_type=%s error=%s "
                "mqtt_connected=%s device_online=%s waiter_count=%s",
                expected,
                type(err).__name__,
                err,
                self._mqtt.connected,
                self.device_online,
                len(self._waiters),
            )
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
            if not self.available:
                continue
            try:
                if self.controller_type == "PS22087B":
                    await self.async_refresh_functions()
                else:
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
        _LOGGER.warning(
            "TMTDIAG MQTT_MESSAGE topic=%s payload_len=%s payload_sha256=%s payload=%s",
            topic,
            len(payload),
            _diag_hash(payload),
            _diag_text(payload),
        )
        if topic == self.tx_topic:
            self.attributes[ATTR_LAST_RESPONSE] = payload
            parsed_parameters = parse_parameter_response(payload)
            parsed_functions = parse_read_function_response(payload)
            if parsed_functions is not None:
                self.function_values = parsed_functions
            _LOGGER.warning(
                "TMTDIAG MQTT_TX_PARSE parameter_parse=%s ack_rs_parse_pending=%s "
                "contains_nak=%s waiter_expectations=%s",
                parsed_parameters is not None,
                True,
                "NAK" in payload,
                [expected for expected, future in self._waiters if not future.done()],
            )
            if parsed_parameters is not None:
                self.parameters = parsed_parameters
                self.attributes[ATTR_DEV_PARAM] = ",".join(map(str, parsed_parameters))
            status = parse_ack_rs(payload)
            _LOGGER.warning(
                "TMTDIAG MQTT_TX_STATUS_PARSE parsed=%s",
                status is not None,
            )
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
                        _LOGGER.warning(
                            "TMTDIAG MQTT_WAITER_MATCH expected=%r payload_sha256=%s",
                            expected,
                            _diag_hash(payload),
                        )
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
            _LOGGER.warning(
                "TMTDIAG SHADOW_PARSE topic=%s json_valid=%s reported_present=%s "
                "reported_keys=%s",
                topic,
                bool(document),
                bool(reported),
                sorted(str(key) for key in reported.keys()) if reported else [],
            )
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
                self.controller_type = fields[1]
                _LOGGER.warning(
                    "TMTDIAG CONTROLLER_IDENTIFIED controller_type=%s "
                    "supported_controller=%s dev_info_len=%s dev_info_sha256=%s",
                    self.controller_type,
                    self.controller_type in _READABLE_CONTROLLERS,
                    len(device_info),
                    _diag_hash(device_info),
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
        _LOGGER.warning(
            "TMTDIAG MQTT_STATE connected=%s device_online=%s state_synchronized=%s",
            connected,
            self.device_online,
            self._state_synchronized,
        )
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
