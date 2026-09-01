"""Small dependency-free async MQTT 3.1.1 client for AWS IoT mutual TLS."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import os
import ssl
import tempfile

from .const import (
    MQTT_KEEPALIVE,
    MQTT_PING_TIMEOUT,
    MQTT_PORT,
    MQTT_RECONNECT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

MessageCallback = Callable[[str, str], Awaitable[None]]
StateCallback = Callable[[bool], None]


class MqttError(Exception):
    """MQTT transport or broker error."""


def _utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise ValueError("MQTT string is too long")
    return len(encoded).to_bytes(2, "big") + encoded


def _remaining_length(value: int) -> bytes:
    result = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 0x80
        result.append(digit)
        if not value:
            return bytes(result)


class AsyncMqttClient:
    """The subset of MQTT needed by one TMT gate."""

    def __init__(
        self,
        endpoint: str,
        client_id: str,
        certificate_pem: str,
        private_key: str,
        topics: tuple[str, ...],
        message_callback: MessageCallback,
        state_callback: StateCallback,
    ) -> None:
        self._endpoint = endpoint
        self._client_id = client_id
        self._certificate_pem = certificate_pem
        self._private_key = private_key
        self._topics = topics
        self._message_callback = message_callback
        self._state_callback = state_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._runner: asyncio.Task[None] | None = None
        self._stopping = False
        self._connected = asyncio.Event()
        self._packet_id = 0

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def async_start(self) -> None:
        """Start reconnecting and wait for the initial connection."""
        self._stopping = False
        self._runner = asyncio.create_task(
            self._run(), name=f"tmt_chow_mqtt_{self._client_id}"
        )
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=30)
        except TimeoutError:
            await self.async_stop()
            raise MqttError("Timed out connecting to AWS IoT") from None

    async def async_stop(self) -> None:
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None
        await self._disconnect()

    async def async_publish(self, topic: str, payload: str) -> None:
        """Publish exactly once at QoS 0; never queue or retry commands."""
        _LOGGER.warning(
            "TMTDIAG MQTT_PUBLISH topic=%s payload_len=%s connected=%s",
            topic,
            len(payload),
            self.connected,
        )
        if not self.connected:
            raise MqttError("AWS IoT is not connected")
        body = _utf8(topic) + payload.encode("utf-8")
        await self._write_packet(0x30, body)

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._connect()
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect boundary
                _LOGGER.warning("TMT Chow MQTT connection lost: %s", err)
            finally:
                await self._disconnect()
            if not self._stopping:
                await asyncio.sleep(MQTT_RECONNECT_SECONDS)

    async def _connect(self) -> None:
        _LOGGER.warning(
            "TMTDIAG MQTT_CONNECT_START endpoint=%s port=%s topic_count=%s",
            self._endpoint,
            MQTT_PORT,
            len(self._topics),
        )
        context = await asyncio.to_thread(self._build_ssl_context)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(
                self._endpoint,
                MQTT_PORT,
                ssl=context,
                server_hostname=self._endpoint,
            ),
            timeout=20,
        )
        variable = _utf8("MQTT") + bytes((4, 0x02)) + MQTT_KEEPALIVE.to_bytes(2, "big")
        await self._write_packet(0x10, variable + _utf8(self._client_id))
        header, body = await asyncio.wait_for(self._read_packet(), timeout=10)
        if header >> 4 != 2 or len(body) < 2 or body[1] != 0:
            raise MqttError("AWS IoT rejected MQTT CONNECT")
        _LOGGER.warning(
            "TMTDIAG MQTT_CONNACK_OK return_code=%s",
            body[1] if len(body) >= 2 else None,
        )
        await self._subscribe()
        self._connected.set()
        self._state_callback(True)

    def _build_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        cert_name: str | None = None
        key_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as cert_file:
                cert_file.write(self._certificate_pem)
                cert_name = cert_file.name
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as key_file:
                key_file.write(self._private_key)
                key_name = key_file.name
            os.chmod(cert_name, 0o600)
            os.chmod(key_name, 0o600)
            context.load_cert_chain(cert_name, key_name)
            return context
        finally:
            for name in (cert_name, key_name):
                if name:
                    with contextlib.suppress(OSError):
                        os.unlink(name)

    async def _subscribe(self) -> None:
        self._packet_id = (self._packet_id % 65535) + 1
        body = self._packet_id.to_bytes(2, "big") + b"".join(
            _utf8(topic) + b"\x00" for topic in self._topics
        )
        await self._write_packet(0x82, body)
        header, response = await asyncio.wait_for(self._read_packet(), timeout=10)
        if (
            header >> 4 != 9
            or len(response) < 3
            or response[:2] != self._packet_id.to_bytes(2, "big")
        ):
            raise MqttError("Invalid MQTT SUBACK")
        _LOGGER.warning(
            "TMTDIAG MQTT_SUBACK packet_id=%s result_codes=%s topics=%s",
            self._packet_id,
            list(response[2:]),
            list(self._topics),
        )
        if any(code == 0x80 for code in response[2:]):
            raise MqttError("AWS IoT rejected an MQTT subscription")

    async def _read_loop(self) -> None:
        while True:
            try:
                header, body = await asyncio.wait_for(
                    self._read_packet(), timeout=MQTT_KEEPALIVE
                )
            except TimeoutError:
                await self._write_packet(0xC0, b"")
                await self._wait_for_ping_response()
                continue
            await self._handle_packet(header, body)

    async def _wait_for_ping_response(self) -> None:
        """Require a timely PINGRESP while still accepting incoming publishes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MQTT_PING_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise MqttError("AWS IoT did not answer MQTT PINGREQ")
            try:
                header, body = await asyncio.wait_for(
                    self._read_packet(), timeout=remaining
                )
            except TimeoutError as err:
                raise MqttError("AWS IoT did not answer MQTT PINGREQ") from err
            if header >> 4 == 13:
                return
            await self._handle_packet(header, body)

    async def _handle_packet(self, header: int, body: bytes) -> None:
        packet_type = header >> 4
        if packet_type == 3:
            if len(body) < 2:
                return
            topic_len = int.from_bytes(body[:2], "big")
            if len(body) < 2 + topic_len:
                return
            offset = 2 + topic_len
            qos = (header >> 1) & 0x03
            if qos:
                offset += 2
            if len(body) < offset:
                return
            topic = body[2 : 2 + topic_len].decode("utf-8", errors="replace")
            payload = body[offset:].decode("utf-8", errors="replace")
            try:
                await self._message_callback(topic, payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad payload must not drop MQTT
                _LOGGER.exception("Failed to process a TMT Chow MQTT message")
        elif packet_type == 14:
            raise MqttError("Broker disconnected")

    async def _read_packet(self) -> tuple[int, bytes]:
        if self._reader is None:
            raise MqttError("MQTT reader is unavailable")
        header = (await self._reader.readexactly(1))[0]
        multiplier = 1
        remaining = 0
        for _ in range(4):
            digit = (await self._reader.readexactly(1))[0]
            remaining += (digit & 0x7F) * multiplier
            if not digit & 0x80:
                return header, await self._reader.readexactly(remaining)
            multiplier *= 128
        raise MqttError("Malformed MQTT remaining length")

    async def _write_packet(self, header: int, body: bytes) -> None:
        if self._writer is None or self._writer.is_closing():
            raise MqttError("MQTT writer is unavailable")
        packet = bytes((header,)) + _remaining_length(len(body)) + body
        async with self._write_lock:
            self._writer.write(packet)
            await self._writer.drain()

    async def _disconnect(self) -> None:
        was_connected = self._connected.is_set()
        self._connected.clear()
        writer, self._writer, self._reader = self._writer, None, None
        if writer:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        if was_connected:
            self._state_callback(False)
