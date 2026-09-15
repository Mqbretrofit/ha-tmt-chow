#!/usr/bin/env python3
"""Read-only OURANOS / ThroughTek IOTC+RDT connectivity probe for TMT Chow.

This helper is intentionally isolated from the Home Assistant runtime. It logs in
to the TMT account, selects a uuid_type=1 device, opens the same class of
ThroughTek IOTC/RDT transport used by the vendor app, and then only performs
PASSIVE RDT reads. It never calls RDT_Write and never sends a gate or parameter
command.

The generated JSON is privacy-safe: username, password, access token and raw
20-character device UID are never written to disk.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import hashlib
import json
import platform
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://installer.tmt-automation.com/"
LOGIN_PATH = "v4.0/user/outh2/token/"
DEVICES_PATH = "v4.0/user/devices/"
OAUTH_CLIENT = (
    "pMFvOSB4KySGR7PDKfMklr4XxbWzyh1Qc0v7JX48:"
    "jNIe1wVDCu14C42U4Jg0CzTG1JobYnpvhhpVh10hwkZKZnP5dBS9kVhZjIxB6CfH"
    "r7eTGT3ccncBnwZeYoor5MbkfLmJphkyBRr5saWOPRaAteTuMELYYfWQKgrVIHH0"
)

DEFAULT_OUTPUT = "tmt_chow_ouranos_probe.json"
KNOWN_BUCKETS = (
    ("admin_devices", "admin"),
    ("user_devices", "user"),
    ("share_devices", "shared"),
)
OURANOS_UUID_TYPE = "1"

# Known-good public ThroughTek starter-kit snapshot used only when the user
# explicitly asks the probe to download an SDK. v0.1 intentionally supports
# Linux x86_64 only for automatic download. Other architectures can still use
# --lib-dir with compatible native Linux libraries supplied by the tester.
SDK_DOWNLOADS: dict[str, dict[str, tuple[str, str]]] = {
    "x86_64": {
        "libIOTCAPIs.so": (
            "https://raw.githubusercontent.com/cloudhsiao/kalay-starter-kit/master/"
            "Lib/Linux/x86_64/libIOTCAPIs.so",
            "f1b0cc09e46a35e329edc16e48b7d04d3570f8cf",
        ),
        "libRDTAPIs.so": (
            "https://raw.githubusercontent.com/cloudhsiao/kalay-starter-kit/master/"
            "Lib/Linux/x86_64/libRDTAPIs.so",
            "bdbabddbab7880b62a5a7e2ac9aa03ca562d57ca",
        ),
    }
}

IOTC_ERRORS = {
    0: "IOTC_ER_NoERROR",
    -1: "IOTC_ER_SERVER_NOT_RESPONSE",
    -2: "IOTC_ER_FAIL_RESOLVE_HOSTNAME",
    -3: "IOTC_ER_ALREADY_INITIALIZED",
    -4: "IOTC_ER_FAIL_CREATE_MUTEX",
    -5: "IOTC_ER_FAIL_CREATE_THREAD",
    -6: "IOTC_ER_FAIL_CREATE_SOCKET",
    -7: "IOTC_ER_FAIL_SOCKET_OPT",
    -8: "IOTC_ER_FAIL_SOCKET_BIND",
    -10: "IOTC_ER_UNLICENSE",
    -12: "IOTC_ER_NOT_INITIALIZED",
    -13: "IOTC_ER_TIMEOUT",
    -14: "IOTC_ER_INVALID_SID",
    -15: "IOTC_ER_UNKNOWN_DEVICE",
    -16: "IOTC_ER_FAIL_GET_LOCAL_IP",
    -18: "IOTC_ER_EXCEED_MAX_SESSION",
    -19: "IOTC_ER_CAN_NOT_FIND_DEVICE",
    -20: "IOTC_ER_CONNECT_IS_CALLING",
    -22: "IOTC_ER_SESSION_CLOSE_BY_REMOTE",
    -23: "IOTC_ER_REMOTE_TIMEOUT_DISCONNECT",
    -24: "IOTC_ER_DEVICE_NOT_LISTENING",
    -27: "IOTC_ER_FAIL_CONNECT_SEARCH",
    -32: "IOTC_ER_TCP_TRAVEL_FAILED",
    -33: "IOTC_ER_TCP_CONNECT_TO_SERVER_FAILED",
    -40: "IOTC_ER_NO_PERMISSION",
    -41: "IOTC_ER_NETWORK_UNREACHABLE",
    -42: "IOTC_ER_FAIL_SETUP_RELAY",
    -43: "IOTC_ER_NOT_SUPPORT_RELAY",
    -44: "IOTC_ER_NO_SERVER_LIST",
    -46: "IOTC_ER_INVALID_ARG",
    -50: "IOTC_ER_SESSION_CLOSED",
    -60: "IOTC_ER_MASTER_NOT_RESPONSE",
    -90: "IOTC_ER_DEVICE_OFFLINE",
}

RDT_ERRORS = {
    -10000: "RDT_ER_NOT_INITIALIZED",
    -10001: "RDT_ER_ALREADY_INITIALIZED",
    -10002: "RDT_ER_EXCEED_MAX_CHANNEL",
    -10003: "RDT_ER_MEM_INSUFF",
    -10004: "RDT_ER_FAIL_CREATE_THREAD",
    -10005: "RDT_ER_FAIL_CREATE_MUTEX",
    -10006: "RDT_ER_RDT_DESTROYED",
    -10007: "RDT_ER_TIMEOUT",
    -10008: "RDT_ER_INVALID_RDT_ID",
    -10009: "RDT_ER_RCV_DATA_END",
    -10010: "RDT_ER_REMOTE_ABORT",
    -10011: "RDT_ER_LOCAL_ABORT",
    -10012: "RDT_ER_CHANNEL_OCCUPIED",
    -10013: "RDT_ER_NO_PERMISSION",
    -10014: "RDT_ER_INVALID_ARG",
    -10015: "RDT_ER_LOCAL_EXIT",
    -10016: "RDT_ER_REMOTE_EXIT",
    -10017: "RDT_ER_SEND_BUFFER_FULL",
    -10018: "RDT_ER_UNCLOSED_CONNECTION_DETECTED",
}


class ProbeError(RuntimeError):
    """Expected probe failure."""


def _url(path: str) -> str:
    return BASE_URL.rstrip("/") + "/" + path.lstrip("/")


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    access_token: str | None = None,
    basic_auth: bool = False,
) -> tuple[int, dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ha-tmt-chow-ouranos-probe/0.1",
    }
    if basic_auth:
        encoded = base64.b64encode(OAUTH_CLIENT.encode()).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    elif access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(_url(path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as err:
        if err.code in (400, 401, 403):
            raise ProbeError(
                f"TMT API rejected the request with HTTP {err.code}. "
                "Check the TMT username and password."
            ) from err
        raise ProbeError(f"TMT API returned HTTP {err.code}.") from err
    except urllib.error.URLError as err:
        raise ProbeError(f"Could not connect to the TMT API: {err.reason}") from err
    except TimeoutError as err:
        raise ProbeError("TMT API request timed out.") from err

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ProbeError("TMT API returned a non-JSON response.") from err
    if not isinstance(payload, dict):
        raise ProbeError("TMT API returned an unexpected JSON root type.")
    return status, payload


def _access_token(payload: dict[str, Any]) -> str:
    for container in (payload, payload.get("data")):
        if isinstance(container, dict):
            value = container.get("access_token")
            if isinstance(value, str) and value:
                return value
    raise ProbeError("Login succeeded but no access token was present in the response.")


def _hash_marker(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]
    return f"sha256:{digest}:len={len(value)}"


def _device_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for bucket, role in KNOWN_BUCKETS:
        rows = payload.get(bucket, []) or []
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            uid = raw.get("uuid")
            uuid_type = raw.get("uuid_type")
            if not isinstance(uid, str) or not uid:
                continue
            if str(uuid_type or "") != OURANOS_UUID_TYPE:
                continue
            candidates.append(
                {
                    "uid": uid,
                    "uuid_type": str(uuid_type),
                    "device_type": str(raw.get("devies_type") or raw.get("device_type") or ""),
                    "product_type": str(raw.get("product_type") or ""),
                    "role": role,
                    "iot_endpoint_present": str(bool(raw.get("iot_endpoint"))).lower(),
                }
            )
    return candidates


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _normalized_machine() -> str:
    machine = platform.machine().lower().replace("amd64", "x86_64")
    if machine in ("x64",):
        return "x86_64"
    if machine in ("arm64",):
        return "aarch64"
    return machine


def _download_sdk(target_dir: Path) -> dict[str, str]:
    if sys.platform != "linux":
        raise ProbeError("Automatic SDK download is supported only on Linux in probe v0.1.")
    machine = _normalized_machine()
    files = SDK_DOWNLOADS.get(machine)
    if files is None:
        raise ProbeError(
            f"Automatic SDK download is not available for {machine!r} in probe v0.1. "
            "Supply compatible native Linux libraries with --lib-dir."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for name, (url, expected_blob_sha) in files.items():
        path = target_dir / name
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
            raise ProbeError(f"Could not download {name}: {err}") from err
        actual_blob_sha = _git_blob_sha1(data)
        if actual_blob_sha != expected_blob_sha:
            raise ProbeError(
                f"Integrity check failed for {name}: expected Git blob "
                f"{expected_blob_sha}, got {actual_blob_sha}."
            )
        path.write_bytes(data)
        path.chmod(0o755)
        result[name] = actual_blob_sha
    return result


def _library_fingerprints(lib_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("libIOTCAPIs.so", "libRDTAPIs.so"):
        path = lib_dir / name
        if not path.is_file():
            raise ProbeError(f"Missing native library: {path}")
        data = path.read_bytes()
        result[name] = f"sha256:{hashlib.sha256(data).hexdigest()}"
    return result


class NativeTutk:
    """Minimal ctypes binding for the read-only connectivity probe."""

    def __init__(self, lib_dir: Path) -> None:
        iotc_path = lib_dir / "libIOTCAPIs.so"
        rdt_path = lib_dir / "libRDTAPIs.so"
        try:
            self.iotc = ctypes.CDLL(str(iotc_path), mode=ctypes.RTLD_GLOBAL)
            self.rdt = ctypes.CDLL(str(rdt_path), mode=ctypes.RTLD_GLOBAL)
        except OSError as err:
            raise ProbeError(
                "Could not load the ThroughTek native libraries. Make sure they match "
                f"this OS/CPU ({sys.platform}/{platform.machine()}): {err}"
            ) from err

        self.iotc.IOTC_Initialize2.argtypes = [ctypes.c_ushort]
        self.iotc.IOTC_Initialize2.restype = ctypes.c_int
        self.iotc.IOTC_Get_SessionID.argtypes = []
        self.iotc.IOTC_Get_SessionID.restype = ctypes.c_int
        self.iotc.IOTC_Connect_ByUID_Parallel.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.iotc.IOTC_Connect_ByUID_Parallel.restype = ctypes.c_int
        self.iotc.IOTC_Session_Close.argtypes = [ctypes.c_int]
        self.iotc.IOTC_Session_Close.restype = ctypes.c_int
        self.iotc.IOTC_DeInitialize.argtypes = []
        self.iotc.IOTC_DeInitialize.restype = ctypes.c_int

        self._connect_stop = getattr(self.iotc, "IOTC_Connect_Stop_BySID", None)
        if self._connect_stop is not None:
            self._connect_stop.argtypes = [ctypes.c_int]
            self._connect_stop.restype = ctypes.c_int

        self.rdt.RDT_Initialize.argtypes = []
        self.rdt.RDT_Initialize.restype = ctypes.c_int
        self.rdt.RDT_Create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_ubyte]
        self.rdt.RDT_Create.restype = ctypes.c_int
        self.rdt.RDT_Read.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.rdt.RDT_Read.restype = ctypes.c_int
        self.rdt.RDT_Destroy.argtypes = [ctypes.c_int]
        self.rdt.RDT_Destroy.restype = ctypes.c_int
        self.rdt.RDT_DeInitialize.argtypes = []
        self.rdt.RDT_DeInitialize.restype = ctypes.c_int

        # Deliberately do not bind RDT_Write in probe v0.1. There is no code path
        # in this file that can transmit an application-level gate command.

    def stop_connect(self, sid: int) -> int | None:
        if self._connect_stop is None:
            return None
        return int(self._connect_stop(sid))


def _error_name(code: int | None, mapping: dict[int, str]) -> str | None:
    if code is None:
        return None
    if code >= 0:
        return "success"
    return mapping.get(code, "unknown_error")


def _connect_with_timeout(
    native: NativeTutk,
    uid: str,
    sid: int,
    timeout_seconds: float,
) -> tuple[int | None, bool, int | None]:
    result: dict[str, int] = {}

    def worker() -> None:
        result["code"] = int(
            native.iotc.IOTC_Connect_ByUID_Parallel(uid.encode("ascii", "strict"), sid)
        )

    thread = threading.Thread(target=worker, name="tmt-ouranos-iotc-connect", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if not thread.is_alive():
        return result.get("code"), False, None

    stop_code = native.stop_connect(sid)
    thread.join(5.0)
    return result.get("code"), True, stop_code


def _passive_rdt_read(
    native: NativeTutk, rdt_id: int, seconds: float
) -> tuple[int, int, list[int]]:
    if seconds <= 0:
        return 0, 0, []
    deadline = time.monotonic() + seconds
    read_count = 0
    total_bytes = 0
    negative_codes: list[int] = []
    buffer = ctypes.create_string_buffer(4096)
    while time.monotonic() < deadline:
        remaining_ms = max(1, min(500, int((deadline - time.monotonic()) * 1000)))
        ret = int(native.rdt.RDT_Read(rdt_id, buffer, len(buffer), remaining_ms))
        if ret > 0:
            read_count += 1
            total_bytes += ret
        elif ret < 0 and ret != -10007:
            negative_codes.append(ret)
            break
    return read_count, total_bytes, negative_codes


def run_probe(
    *,
    username: str,
    password: str,
    lib_dir: Path,
    device_index: int,
    channel: int,
    connect_timeout: float,
    rdt_timeout_ms: int,
    listen_seconds: float,
) -> dict[str, Any]:
    login_status, login_payload = _request(
        "POST",
        LOGIN_PATH,
        body={
            "username": username,
            "password": password,
            "grant_type": "password",
            "scope": "user",
            "app_type_index": 1,
        },
        basic_auth=True,
    )
    token = _access_token(login_payload)
    devices_status, devices_payload = _request("GET", DEVICES_PATH, access_token=token)
    candidates = _device_candidates(devices_payload)
    if not candidates:
        raise ProbeError("No uuid_type=1 (OURANOS) device was found in this TMT account.")
    if device_index < 0 or device_index >= len(candidates):
        raise ProbeError(
            f"--device-index {device_index} is out of range; found {len(candidates)} OURANOS device(s)."
        )
    device = candidates[device_index]
    uid = device["uid"]
    if len(uid) != 20:
        raise ProbeError(
            f"Selected OURANOS identifier length is {len(uid)}, expected 20. "
            "Refusing native connection because the observed TMT OURANOS path uses a 20-character UID."
        )
    try:
        uid.encode("ascii", "strict")
    except UnicodeEncodeError as err:
        raise ProbeError("Selected OURANOS UID is not ASCII; refusing native connection.") from err

    native = NativeTutk(lib_dir)
    report: dict[str, Any] = {
        "probe": {
            "name": "ha-tmt-chow OURANOS/TUTK connectivity probe",
            "version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "safety": {
                "login_request_sent": True,
                "device_list_request_sent": True,
                "mqtt_connected": False,
                "aws_certificate_requested": False,
                "aws_policy_requested": False,
                "iotc_connect_attempted": False,
                "rdt_create_attempted": False,
                "rdt_passive_read_attempted": False,
                "rdt_write_bound": False,
                "rdt_write_called": False,
                "gate_command_sent": False,
                "parameter_read_command_sent": False,
                "parameter_write_command_sent": False,
            },
            "privacy": {
                "username_written": False,
                "password_written": False,
                "access_token_written": False,
                "raw_uid_written": False,
                "remote_ip_written": False,
            },
        },
        "environment": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "library_fingerprints": _library_fingerprints(lib_dir),
        },
        "http": {"login_status": login_status, "devices_status": devices_status},
        "selection": {
            "ouranos_candidates": len(candidates),
            "selected_index": device_index,
            "uuid_hash": _hash_marker(uid),
            "uuid_length": len(uid),
            "uuid_type": device["uuid_type"],
            "device_type": device["device_type"],
            "product_type": device["product_type"],
            "role": device["role"],
            "iot_endpoint_present": device["iot_endpoint_present"] == "true",
        },
        "transport": {
            "channel": channel,
            "connect_timeout_seconds": connect_timeout,
            "rdt_create_timeout_ms": rdt_timeout_ms,
            "passive_listen_seconds": listen_seconds,
            "iotc_initialize_code": None,
            "iotc_initialize_name": None,
            "rdt_initialize_code": None,
            "rdt_initialize_name": None,
            "session_id": None,
            "iotc_connect_code": None,
            "iotc_connect_name": None,
            "iotc_connect_timed_out": False,
            "iotc_connect_stop_code": None,
            "iotc_connected": False,
            "rdt_create_code": None,
            "rdt_create_name": None,
            "rdt_connected": False,
            "passive_read_count": 0,
            "passive_read_bytes": 0,
            "passive_read_negative_codes": [],
            "cleanup": {},
        },
    }

    t = report["transport"]
    safety = report["probe"]["safety"]
    sid: int | None = None
    rdt_id: int | None = None
    iotc_initialized = False
    rdt_initialized = False

    try:
        iotc_init = int(native.iotc.IOTC_Initialize2(0))
        t["iotc_initialize_code"] = iotc_init
        t["iotc_initialize_name"] = _error_name(iotc_init, IOTC_ERRORS)
        if iotc_init not in (0, -3):
            return report
        iotc_initialized = True

        rdt_init = int(native.rdt.RDT_Initialize())
        t["rdt_initialize_code"] = rdt_init
        t["rdt_initialize_name"] = _error_name(rdt_init, RDT_ERRORS)
        if rdt_init <= 0 and rdt_init != -10001:
            return report
        rdt_initialized = True

        sid = int(native.iotc.IOTC_Get_SessionID())
        t["session_id"] = sid if sid >= 0 else None
        if sid < 0:
            t["iotc_connect_code"] = sid
            t["iotc_connect_name"] = _error_name(sid, IOTC_ERRORS)
            return report

        safety["iotc_connect_attempted"] = True
        connect_code, timed_out, stop_code = _connect_with_timeout(
            native, uid, sid, connect_timeout
        )
        t["iotc_connect_code"] = connect_code
        t["iotc_connect_name"] = _error_name(connect_code, IOTC_ERRORS)
        t["iotc_connect_timed_out"] = timed_out
        t["iotc_connect_stop_code"] = stop_code
        if connect_code is None or connect_code < 0:
            return report
        t["iotc_connected"] = True

        safety["rdt_create_attempted"] = True
        rdt_id = int(native.rdt.RDT_Create(sid, rdt_timeout_ms, channel))
        t["rdt_create_code"] = rdt_id
        t["rdt_create_name"] = _error_name(rdt_id, RDT_ERRORS)
        if rdt_id < 0:
            return report
        t["rdt_connected"] = True

        if listen_seconds > 0:
            safety["rdt_passive_read_attempted"] = True
            reads, total, negatives = _passive_rdt_read(native, rdt_id, listen_seconds)
            t["passive_read_count"] = reads
            t["passive_read_bytes"] = total
            t["passive_read_negative_codes"] = [
                {"code": code, "name": _error_name(code, RDT_ERRORS)} for code in negatives
            ]
        return report
    finally:
        cleanup = t["cleanup"]
        if rdt_id is not None and rdt_id >= 0:
            try:
                cleanup["rdt_destroy_code"] = int(native.rdt.RDT_Destroy(rdt_id))
            except Exception as err:  # pragma: no cover
                cleanup["rdt_destroy_error"] = type(err).__name__
        if sid is not None and sid >= 0:
            try:
                cleanup["iotc_session_close_code"] = int(native.iotc.IOTC_Session_Close(sid))
            except Exception as err:  # pragma: no cover
                cleanup["iotc_session_close_error"] = type(err).__name__
        if rdt_initialized:
            try:
                cleanup["rdt_deinitialize_code"] = int(native.rdt.RDT_DeInitialize())
            except Exception as err:  # pragma: no cover
                cleanup["rdt_deinitialize_error"] = type(err).__name__
        if iotc_initialized:
            try:
                cleanup["iotc_deinitialize_code"] = int(native.iotc.IOTC_DeInitialize())
            except Exception as err:  # pragma: no cover
                cleanup["iotc_deinitialize_error"] = type(err).__name__


def _self_test() -> None:
    payload = {
        "admin_devices": [
            {
                "uuid": "ABCDEFGHIJKLMNOPQRST",
                "uuid_type": "1",
                "devies_type": "PS19001",
                "product_type": "108",
                "iot_endpoint": None,
            },
            {
                "uuid": "47dcb168-6913-4a5b-9294-121300c6fbbf",
                "uuid_type": "5",
                "devies_type": "PS25007",
                "product_type": "113",
                "iot_endpoint": "example.invalid",
            },
        ]
    }
    candidates = _device_candidates(payload)
    if len(candidates) != 1:
        raise AssertionError(f"Expected one OURANOS candidate, got {len(candidates)}")
    selected = candidates[0]
    if selected["device_type"] != "PS19001" or selected["uuid_type"] != "1":
        raise AssertionError("OURANOS selection lost device metadata")
    marker = _hash_marker(selected["uid"])
    if selected["uid"] in marker or "ABCDEFGHIJKLMNOPQRST" in marker:
        raise AssertionError("UID hash marker leaked the raw UID")
    sample = b"abc123"
    expected = hashlib.sha1(b"blob 6\0" + sample).hexdigest()
    if _git_blob_sha1(sample) != expected:
        raise AssertionError("Git blob integrity helper is wrong")
    if hasattr(NativeTutk, "RDT_Write"):
        raise AssertionError("Probe v0.1 must not expose an RDT_Write helper")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only TMT Chow OURANOS/TUTK IOTC+RDT connectivity probe. "
            "Probe v0.1 never calls RDT_Write and never sends a gate command."
        )
    )
    parser.add_argument("--username", help="TMT Chow username; prompts when omitted.")
    parser.add_argument(
        "--lib-dir",
        type=Path,
        help="Directory containing compatible libIOTCAPIs.so and libRDTAPIs.so.",
    )
    parser.add_argument(
        "--download-sdk",
        action="store_true",
        help=(
            "Download the pinned public ThroughTek starter-kit libraries for the "
            "current supported architecture (v0.1: Linux x86_64)."
        ),
    )
    parser.add_argument(
        "--sdk-cache-dir",
        type=Path,
        default=Path(".tmt_chow_probe_sdk") / _normalized_machine(),
        help="Where --download-sdk stores the native libraries.",
    )
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--channel", type=int, default=0, choices=range(0, 32))
    parser.add_argument("--connect-timeout", type=float, default=25.0)
    parser.add_argument("--rdt-timeout-ms", type=int, default=10000)
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=2.0,
        help="Passive RDT read window after connection; sends no data.",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run offline safety/selection tests and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        _self_test()
        print("Self-test OK: OURANOS selection/privacy/integrity checks passed.")
        print("Safety: probe v0.1 contains no RDT_Write call path.")
        return 0

    if args.lib_dir is not None and args.download_sdk:
        print("ERROR: use either --lib-dir or --download-sdk, not both.", file=sys.stderr)
        return 2

    lib_dir: Path
    if args.download_sdk:
        lib_dir = args.sdk_cache_dir.resolve()
        print(f"Downloading pinned ThroughTek probe libraries to: {lib_dir}")
        try:
            _download_sdk(lib_dir)
        except ProbeError as err:
            print(f"ERROR: {err}", file=sys.stderr)
            return 2
    elif args.lib_dir is not None:
        lib_dir = args.lib_dir.resolve()
    else:
        print(
            "ERROR: native ThroughTek libraries are required. Use --download-sdk "
            "(Linux x86_64) or --lib-dir PATH.",
            file=sys.stderr,
        )
        return 2

    username = (args.username or input("TMT Chow username: ")).strip()
    if not username:
        print("ERROR: username is required.", file=sys.stderr)
        return 2
    password = getpass.getpass("TMT Chow password: ")
    if not password:
        print("ERROR: password is required.", file=sys.stderr)
        return 2

    output = Path(args.output)
    try:
        report = run_probe(
            username=username,
            password=password,
            lib_dir=lib_dir,
            device_index=args.device_index,
            channel=args.channel,
            connect_timeout=max(1.0, args.connect_timeout),
            rdt_timeout_ms=max(1000, args.rdt_timeout_ms),
            listen_seconds=max(0.0, args.listen_seconds),
        )
    except ProbeError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 1

    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    transport = report["transport"]
    print(f"Report written to: {output}")
    print(
        "Result: "
        f"IOTC connected={transport['iotc_connected']}, "
        f"RDT connected={transport['rdt_connected']}, "
        f"RDT code={transport['rdt_create_code']} ({transport['rdt_create_name']})"
    )
    print("Safety: no RDT_Write, gate command, or parameter command was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
