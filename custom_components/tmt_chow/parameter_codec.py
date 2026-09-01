"""Encode/decode TMT parameter payloads using the vendor APK model metadata."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from .model_parameter_schemas import parameter_options, parameter_schema_for
from .model_protocol_profiles import HEX_DIGITS, protocol_profile_for

# Schema tuple indexes. Kept local so the generated data stays compact.
_KIND = 0
_KEY = 1
_TYPE = 3
_DEFAULT = 5
_OFFSET = 6
_MAX_HINT = 7
_BIT_INDEX = 8
_BIG_ENDIAN = 9
_BIT_COUNT = 10
_MINIMUM = 11
_MAXIMUM = 12
_INCREMENT = 13
_MULTIPLE = 14


class ParameterCodecError(ValueError):
    """The controller parameter payload cannot be encoded or decoded safely."""


@dataclass(slots=True, frozen=True)
class ParameterTransport:
    """Commands and acknowledgements for one controller's UART generation."""

    uart_version: int
    read_command: str
    read_ack: str
    write_ack: str


def parameter_transport_for(controller_type: str | None) -> ParameterTransport | None:
    """Return read/write transport metadata for a known controller."""
    profile = protocol_profile_for(controller_type)
    if profile is None:
        return None
    uart_version = profile[0]
    if uart_version == 0:
        return ParameterTransport(0, "READ FUNCTION", "ACK READ FUNCTION", "ACK FUNCTION")
    return ParameterTransport(1, "RP,1", "ACK RP,1", "ACK WP")


def parameter_defaults(controller_type: str | None) -> tuple[int, ...] | None:
    """Return the model's APK defaults in raw logical-value units."""
    schema = parameter_schema_for(controller_type)
    if schema is None:
        return None
    return tuple(int(spec[_DEFAULT] or 0) for spec in schema)


def is_editable_parameter(spec: tuple) -> bool:
    """Return whether the APK exposes a schema entry as a user parameter."""
    parameter_type = int(spec[_TYPE] or 0)
    return parameter_type < 10 and parameter_type != 4


def validate_model_parameter_values(
    controller_type: str | None, values: Sequence[int]
) -> tuple[int, ...]:
    """Validate a full model value vector and return normalized integers."""
    schema = parameter_schema_for(controller_type)
    if schema is None:
        raise ParameterCodecError("Unknown controller parameter schema")
    if len(values) != len(schema):
        raise ParameterCodecError(
            f"Parameter count mismatch: expected {len(schema)}, got {len(values)}"
        )
    normalized = tuple(int(value) for value in values)
    for index, (spec, value) in enumerate(zip(schema, normalized, strict=True)):
        if not is_editable_parameter(spec):
            continue
        options = parameter_options(spec)
        if options:
            if not 0 <= value < len(options):
                raise ParameterCodecError(
                    f"Parameter {index + 1} is outside its option range"
                )
            continue
        minimum = spec[_MINIMUM]
        maximum = spec[_MAXIMUM]
        if minimum is not None and value < int(minimum):
            raise ParameterCodecError(f"Parameter {index + 1} is below its minimum")
        if maximum is not None and value > int(maximum):
            raise ParameterCodecError(f"Parameter {index + 1} is above its maximum")
        increment = spec[_INCREMENT]
        if increment not in (None, 0):
            origin = int(minimum or 0)
            if (value - origin) % int(increment) != 0:
                raise ParameterCodecError(
                    f"Parameter {index + 1} does not match its increment"
                )
    return normalized


def parameter_native_scale(spec: tuple) -> float:
    """Return the Android numeric display multiplier."""
    multiple = spec[_MULTIPLE]
    return float(multiple) if multiple not in (None, 0) else 1.0


def parameter_raw_to_native(spec: tuple, value: int) -> float:
    """Convert a raw integer parameter to the value shown by the vendor UI."""
    return int(value) * parameter_native_scale(spec)


def parameter_native_to_raw(spec: tuple, value: float) -> int:
    """Convert a vendor-UI numeric value back to its raw integer value."""
    scale = parameter_native_scale(spec)
    raw = int(round(float(value) / scale))
    minimum = spec[_MINIMUM]
    maximum = spec[_MAXIMUM]
    if minimum is not None and raw < int(minimum):
        raise ParameterCodecError("Parameter value is below its minimum")
    if maximum is not None and raw > int(maximum):
        raise ParameterCodecError("Parameter value is above its maximum")
    increment = spec[_INCREMENT]
    if increment not in (None, 0):
        origin = int(minimum or 0)
        if (raw - origin) % int(increment) != 0:
            raise ParameterCodecError("Parameter value does not match its increment")
    return raw


def encode_model_parameter_write(
    controller_type: str | None, values: Sequence[int]
) -> str:
    """Build the complete vendor write command for a known controller model."""
    schema = parameter_schema_for(controller_type)
    profile = protocol_profile_for(controller_type)
    if schema is None or profile is None:
        raise ParameterCodecError("Unknown controller parameter protocol")
    normalized = validate_model_parameter_values(controller_type, values)
    uart, skips, codec_profile, ext_suffix = profile

    if codec_profile == "legacy_base":
        fragment = _encode_legacy(schema, normalized, uart, skips, ext_suffix)
    elif codec_profile in {"new_phase1", "custom_p170"}:
        fragment = _encode_new_phase1(schema, normalized, uart, skips, ext_suffix)
    elif codec_profile == "converted_bits":
        raw = _encode_parameter_values(schema, normalized)
        fragment = _encode_converted(schema, raw, uart, skips, ext_suffix)
    elif codec_profile == "converted_swap_8_9":
        raw = list(_encode_parameter_values(schema, normalized))
        if len(raw) <= 9:
            raise ParameterCodecError("Swap codec schema is unexpectedly short")
        raw[8], raw[9] = raw[9], raw[8]
        fragment = _encode_converted(schema, tuple(raw), uart, skips, ext_suffix)
    elif codec_profile == "custom_a510":
        fragment = _encode_a510(schema, normalized, ext_suffix)
    elif codec_profile == "custom_p100":
        fragment = _encode_p100(schema, normalized, ext_suffix)
    elif codec_profile == "custom_split_pair":
        fragment = _encode_split_pair(schema, normalized, ext_suffix)
    elif codec_profile == "custom_csv6":
        fragment = _encode_csv6(schema, normalized, ext_suffix)
    else:
        raise ParameterCodecError(f"Unsupported parameter codec: {codec_profile}")

    if uart == 0:
        return "WRITE FUNCTION" + fragment
    return "WP,1:" + fragment


def decode_model_parameter_response(
    controller_type: str | None, payload: str
) -> tuple[int, ...] | None:
    """Decode a vendor read response into the model's full logical value vector."""
    schema = parameter_schema_for(controller_type)
    profile = protocol_profile_for(controller_type)
    if schema is None or profile is None or not isinstance(payload, str):
        return None
    uart, skips, codec_profile, _ = profile
    fragment = _extract_read_fragment(payload, uart)
    if fragment is None:
        return None
    try:
        if codec_profile == "legacy_base":
            return _decode_legacy(schema, fragment, uart, skips)
        if codec_profile in {"new_phase1", "custom_p170"}:
            return _decode_new_phase1(schema, fragment, uart, skips)
        if codec_profile == "converted_bits":
            raw = _decode_converted(schema, fragment, uart, skips)
            return _decode_parameter_values(schema, raw)
        if codec_profile == "converted_swap_8_9":
            raw = _decode_converted(schema, fragment, uart, skips)
            logical = list(_decode_parameter_values(schema, raw))
            if len(logical) <= 8:
                return None
            value = logical[8]
            logical[8] = ((value & 1) << 1) + ((value & 2) >> 1)
            return tuple(logical)
        if codec_profile == "custom_a510":
            return _decode_a510(schema, fragment)
        if codec_profile == "custom_p100":
            return _decode_p100(schema, fragment)
        if codec_profile == "custom_split_pair":
            return _decode_split_pair(schema, fragment)
        if codec_profile == "custom_csv6":
            return _decode_csv6(schema, fragment)
    except (IndexError, TypeError, ValueError, ParameterCodecError):
        return None
    return None


def _extract_read_fragment(payload: str, uart: int) -> str | None:
    clean = payload.split(";", 1)[0].strip()
    if uart == 0:
        marker = "ACK READ FUNCTION"
        pos = clean.find(marker)
        if pos < 0:
            # Allow diagnostics/shadow data that already contains just the wire body.
            return clean if ":" in clean else None
        tail = clean[pos + len(marker) :]
        return tail[1:] if tail[:1] in {",", ":"} else tail
    marker = "ACK RP,1:"
    pos = clean.find(marker)
    if pos >= 0:
        return clean[pos + len(marker) :]
    # Some vendor paths report ACK RP rather than the more specific ACK RP,1.
    match = re.search(r"ACK RP(?:,1)?:(.*)$", clean)
    if match:
        return match.group(1)
    # DEV PARAM shadow values are already the body.
    return clean.lstrip(":") if clean and "ACK " not in clean else None


def _spec_max(spec: tuple) -> int:
    hint = int(spec[_MAX_HINT] or 0)
    if hint > 0:
        return hint
    maximum = spec[_MAXIMUM]
    if maximum is not None:
        return int(maximum)
    options = parameter_options(spec)
    return max(0, len(options) - 1)


def _format_wire_value(spec: tuple, value: int, uart: int) -> str:
    if uart != 0:
        return str(int(value))
    parameter_type = int(spec[_TYPE] or 0)
    if parameter_type == 1:
        return str(int(value))
    maximum = _spec_max(spec)
    width = len(str(maximum))
    if width <= 1:
        return f"{int(value):0{max(1, width)}d}"
    return f"{int(value):0{width}X}"


def _parse_wire_value(spec: tuple, token: str, uart: int, *, phase1: bool = False) -> int:
    raw = token.split(":", 1)[1] if ":" in token else token
    raw = raw.strip()
    if raw == "":
        raise ParameterCodecError("Empty wire value")
    if uart != 0:
        return int(raw, 10)
    if phase1 and len(str(_spec_max(spec))) > 1:
        return int(raw, 16)
    try:
        return int(raw, 10)
    except ValueError:
        try:
            return int(raw, 16)
        except ValueError:
            first = raw[0]
            if first not in HEX_DIGITS:
                raise ParameterCodecError("Invalid UART0 encoded value") from None
            return HEX_DIGITS.index(first)


def _tokenize(fragment: str) -> list[str]:
    # Python preserves internal empty CSV fields, which UART1 uses for skips.
    return fragment.split(",") if fragment != "" else []


def _next_wire(tokens: list[str], wire: int, skips: Sequence[int]) -> tuple[str, int]:
    skip_set = set(skips)
    while wire in skip_set:
        wire += 1
    if wire >= len(tokens):
        raise ParameterCodecError("Parameter response is shorter than the model schema")
    return tokens[wire], wire + 1


def _append_wire(
    out: list[str], wire: int, value: str, uart: int, skips: Sequence[int]
) -> int:
    skip_set = set(skips)
    while wire in skip_set:
        out.append(f"{HEX_DIGITS[wire]}:0" if uart == 0 else "")
        wire += 1
    out.append(f"{HEX_DIGITS[wire]}:{value}" if uart == 0 else value)
    return wire + 1


def _finish_fragment(out: list[str], uart: int, ext_suffix: str) -> str:
    body = ",".join(out)
    if uart == 0:
        body = "," + body
    return body + (ext_suffix or "")


def _encode_legacy(schema, values, uart, skips, ext_suffix) -> str:
    out: list[str] = []
    wire = 0
    for spec, value in zip(schema, values, strict=True):
        if int(spec[_TYPE] or 0) >= 10:
            continue
        encoded = int(value) + int(spec[_OFFSET] or 0)
        wire = _append_wire(out, wire, _format_wire_value(spec, encoded, uart), uart, skips)
    return _finish_fragment(out, uart, ext_suffix)


def _decode_legacy(schema, fragment, uart, skips) -> tuple[int, ...]:
    result = list(int(spec[_DEFAULT] or 0) for spec in schema)
    tokens = _tokenize(fragment)
    wire = 0
    for index, spec in enumerate(schema):
        if int(spec[_TYPE] or 0) >= 10:
            continue
        token, wire = _next_wire(tokens, wire, skips)
        result[index] = _parse_wire_value(spec, token, uart) - int(spec[_OFFSET] or 0)
    return tuple(result)


def _encode_new_phase1(schema, values, uart, skips, ext_suffix) -> str:
    out: list[str] = []
    wire = 0
    for spec, value in zip(schema, values, strict=True):
        parameter_type = int(spec[_TYPE] or 0)
        if parameter_type >= 10:
            continue
        if parameter_type == 4:
            wire = _append_wire(out, wire, "0", uart, skips)
            continue
        encoded = int(value) + int(spec[_OFFSET] or 0)
        bit_count = int(spec[_BIT_COUNT] or 0)
        if bit_count > 0:
            bits = [(encoded >> bit) & 1 for bit in range(bit_count)]
            if bool(spec[_BIG_ENDIAN]):
                bits.reverse()
            for bit in bits:
                wire = _append_wire(
                    out,
                    wire,
                    _format_wire_value(spec, bit, uart),
                    uart,
                    skips,
                )
        else:
            wire = _append_wire(
                out,
                wire,
                _format_wire_value(spec, encoded, uart),
                uart,
                skips,
            )
    return _finish_fragment(out, uart, ext_suffix)


def _decode_new_phase1(schema, fragment, uart, skips) -> tuple[int, ...]:
    result = list(int(spec[_DEFAULT] or 0) for spec in schema)
    tokens = _tokenize(fragment)
    wire = 0
    for index, spec in enumerate(schema):
        parameter_type = int(spec[_TYPE] or 0)
        if parameter_type >= 10:
            continue
        bit_count = int(spec[_BIT_COUNT] or 0)
        count = bit_count if bit_count > 0 else 1
        wire_values: list[int] = []
        for _ in range(count):
            token, wire = _next_wire(tokens, wire, skips)
            try:
                raw = _parse_wire_value(spec, token, uart, phase1=True)
            except ParameterCodecError:
                raw = 0
            wire_values.append(raw - int(spec[_OFFSET] or 0))
        if bit_count > 0:
            if bool(spec[_BIG_ENDIAN]):
                value = 0
                for bit in wire_values:
                    value = (value << 1) | (bit & 1)
            else:
                value = sum((bit & 1) << bit_index for bit_index, bit in enumerate(wire_values))
            result[index] = value
        else:
            result[index] = wire_values[0]
    return tuple(result)


def _encode_parameter_values(schema, values) -> tuple[int, ...]:
    raw = [0] * len(schema)
    for index, spec in enumerate(schema):
        if int(spec[_TYPE] or 0) == 4:
            continue
        value = int(values[index])
        key = spec[_KEY]
        for raw_index, raw_spec in enumerate(schema):
            if raw_spec[_KEY] != key:
                continue
            bit_index = raw_spec[_BIT_INDEX]
            if bit_index is None or int(bit_index) < 0:
                raw[raw_index] = value
            else:
                raw[raw_index] = (value >> int(bit_index)) & 1
    return tuple(raw)


def _decode_parameter_values(schema, raw_values) -> tuple[int, ...]:
    result = [0] * len(schema)
    first_by_key: dict[str, int] = {}
    for index, spec in enumerate(schema):
        first_by_key.setdefault(str(spec[_KEY]), index)
    for raw_index, spec in enumerate(schema):
        logical_index = first_by_key.get(str(spec[_KEY]))
        if logical_index is None:
            continue
        bit_index = spec[_BIT_INDEX]
        if bit_index is None or int(bit_index) < 0:
            result[logical_index] = int(raw_values[raw_index])
        else:
            result[logical_index] |= (int(raw_values[raw_index]) & 1) << int(bit_index)
    return tuple(result)


def _encode_converted(schema, raw_values, uart, skips, ext_suffix) -> str:
    out: list[str] = []
    wire = 0
    for spec, value in zip(schema, raw_values, strict=True):
        if int(spec[_TYPE] or 0) >= 10:
            continue
        encoded = int(value) + int(spec[_OFFSET] or 0)
        wire = _append_wire(out, wire, str(encoded), uart, skips)
    return _finish_fragment(out, uart, ext_suffix)


def _decode_converted(schema, fragment, uart, skips) -> tuple[int, ...]:
    result = list(int(spec[_DEFAULT] or 0) for spec in schema)
    tokens = _tokenize(fragment)
    wire = 0
    for index, spec in enumerate(schema):
        if int(spec[_TYPE] or 0) >= 10:
            continue
        token, wire = _next_wire(tokens, wire, skips)
        result[index] = _parse_wire_value(spec, token, uart) - int(spec[_OFFSET] or 0)
    return tuple(result)


def _uart0_custom_fragment(schema, wire_sources, ext_suffix: str) -> str:
    out=[]
    for wire,(source_index,value) in enumerate(wire_sources):
        spec=schema[source_index]
        encoded=int(value)+int(spec[_OFFSET] or 0)
        out.append(f"{HEX_DIGITS[wire]}:{_format_wire_value(spec,encoded,0)}")
    return _finish_fragment(out,0,ext_suffix)


def _decode_uart0_custom_tokens(fragment: str) -> list[str]:
    return _tokenize(fragment)


def _encode_a510(schema, values, ext_suffix) -> str:
    # Vendor A510 layout: logical #3 is split over two UART fields and wire #5
    # is a constant compatibility slot that consumes no logical parameter.
    sources=[]
    for logical in range(len(schema)):
        value=int(values[logical])
        if logical==2:
            sources.append((logical,value//2)); sources.append((logical,value%2))
        elif logical==4:
            sources.append((logical,1))
            sources.append((logical,value))
        else:
            sources.append((logical,value))
    return _uart0_custom_fragment(schema,sources,ext_suffix)


def _decode_a510(schema, fragment) -> tuple[int, ...]:
    tokens=_decode_uart0_custom_tokens(fragment)
    defaults=list(int(spec[_DEFAULT] or 0) for spec in schema)
    if len(tokens)<len(schema)+2:
        raise ParameterCodecError("A510 response is too short")
    # wire 2+3 -> logical 2; wire 5 is ignored.
    mapping=[0,1,None,None,3,None,4,5,6,7]
    defaults[0]=_parse_wire_value(schema[0],tokens[0],0)-int(schema[0][_OFFSET] or 0)
    defaults[1]=_parse_wire_value(schema[1],tokens[1],0)-int(schema[1][_OFFSET] or 0)
    hi=_parse_wire_value(schema[2],tokens[2],0); lo=_parse_wire_value(schema[2],tokens[3],0)
    defaults[2]=hi*2+lo-int(schema[2][_OFFSET] or 0)
    for logical in range(3, len(schema)):
        wire = logical + (1 if logical == 3 else 2)
        defaults[logical] = (
            _parse_wire_value(schema[logical], tokens[wire], 0)
            - int(schema[logical][_OFFSET] or 0)
        )
    return tuple(defaults)


def _encode_p100(schema, values, ext_suffix) -> str:
    sources=[]
    for logical in range(len(schema)):
        value=int(values[logical])
        if logical==1:
            sources.append((logical,value//2)); sources.append((logical,value%2))
        else:
            sources.append((logical,value))
    return _uart0_custom_fragment(schema,sources,ext_suffix)


def _decode_p100(schema, fragment) -> tuple[int, ...]:
    tokens=_decode_uart0_custom_tokens(fragment)
    defaults=list(int(spec[_DEFAULT] or 0) for spec in schema)
    if len(tokens)<len(schema)+1:
        raise ParameterCodecError("P100 response is too short")
    defaults[0]=_parse_wire_value(schema[0],tokens[0],0)-int(schema[0][_OFFSET] or 0)
    hi=_parse_wire_value(schema[1],tokens[1],0); lo=_parse_wire_value(schema[1],tokens[2],0)
    defaults[1]=hi*2+lo-int(schema[1][_OFFSET] or 0)
    for logical in range(2,len(schema)):
        wire=logical+1
        defaults[logical]=_parse_wire_value(schema[logical],tokens[wire],0)-int(schema[logical][_OFFSET] or 0)
    return tuple(defaults)


def _encode_split_pair(schema, values, ext_suffix) -> str:
    # Models PS19075/PS20113 carry logical index 1 in wire slots 1 and 2;
    # index 2 is the APK's hidden continuation parameter.
    out=[]
    for wire in range(7):
        if wire==0:
            out.append(str(int(values[0])+int(schema[0][_OFFSET] or 0)))
        elif wire==1:
            value=int(values[1])
            out.append(str(value>>1)); out.append(str(value&1))
        elif wire==2:
            continue
        else:
            out.append(str(int(values[wire])+int(schema[wire][_OFFSET] or 0)))
    return ",".join(out)+(ext_suffix or "")


def _decode_split_pair(schema, fragment) -> tuple[int, ...]:
    tokens=_tokenize(fragment)
    if len(tokens)<7:
        raise ParameterCodecError("Split-pair response is too short")
    result=list(int(spec[_DEFAULT] or 0) for spec in schema)
    result[0]=int(tokens[0])-int(schema[0][_OFFSET] or 0)
    result[1]=(int(tokens[1])<<1)+int(tokens[2])
    for index in range(3,min(7,len(schema))):
        result[index]=int(tokens[index])-int(schema[index][_OFFSET] or 0)
    return tuple(result)


def _encode_csv6(schema, values, ext_suffix) -> str:
    out=[]
    for index in range(min(6,len(schema))):
        out.append(str(int(values[index])+int(schema[index][_OFFSET] or 0)))
    return ",".join(out)+(ext_suffix or "")


def _decode_csv6(schema, fragment) -> tuple[int, ...]:
    tokens=_tokenize(fragment)
    if len(tokens)<6:
        raise ParameterCodecError("CSV6 response is too short")
    result=list(int(spec[_DEFAULT] or 0) for spec in schema)
    for index in range(min(6,len(schema))):
        result[index]=int(tokens[index])-int(schema[index][_OFFSET] or 0)
    return tuple(result)