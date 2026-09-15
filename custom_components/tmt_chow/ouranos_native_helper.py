#!/usr/bin/env python3
"""Short-lived read-only native TUTK helper used by Home Assistant.

The 20-character UID is supplied on stdin and is never printed by this helper.
It intentionally has no RDT_Write binding and no application command payload.
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

IOTC_ERRORS = {
    -1: "IOTC_ER_SERVER_NOT_RESPONSE",
    -2: "IOTC_ER_FAIL_RESOLVE_HOSTNAME",
    -3: "IOTC_ER_ALREADY_INITIALIZED",
    -10: "IOTC_ER_UNLICENSE",
    -12: "IOTC_ER_NOT_INITIALIZED",
    -13: "IOTC_ER_TIMEOUT",
    -14: "IOTC_ER_INVALID_SID",
    -15: "IOTC_ER_UNKNOWN_DEVICE",
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
    -1004: "TUTK_ER_INVALID_LICENSE_KEY",
    -1005: "TUTK_ER_NO_LICENSE_KEY",
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
}

REQUIRED_IOTC = (
    "IOTC_Initialize2",
    "IOTC_Get_SessionID",
    "IOTC_Connect_ByUID_Parallel",
    "IOTC_Session_Close",
    "IOTC_DeInitialize",
)
RDT_SYMBOLS = (
    "RDT_Initialize",
    "RDT_Create",
    "RDT_Read",
    "RDT_Destroy",
    "RDT_DeInitialize",
)


def _error_name(code: int | None, table: dict[int, str]) -> str | None:
    if code is None:
        return None
    if code >= 0:
        return "success"
    return table.get(code, "unknown_error")


def _connect(
    lib: ctypes.CDLL, uid: str, sid: int, timeout: float
) -> tuple[int | None, bool, int | None]:
    result: dict[str, int] = {}

    def worker() -> None:
        result["code"] = int(
            lib.IOTC_Connect_ByUID_Parallel(uid.encode("ascii"), sid)
        )

    thread = threading.Thread(target=worker, name="tmt-iotc-connect", daemon=True)
    thread.start()
    thread.join(timeout)
    if not thread.is_alive():
        return result.get("code"), False, None

    stop_code: int | None = None
    stop = getattr(lib, "IOTC_Connect_Stop_BySID", None)
    if stop is not None:
        stop.argtypes = [ctypes.c_int]
        stop.restype = ctypes.c_int
        stop_code = int(stop(sid))
        thread.join(3.0)
    return result.get("code"), True, stop_code


def _new_report() -> dict[str, Any]:
    return {
        "library_loaded": False,
        "library_error": None,
        "symbols": {},
        "iotc_initialize_code": None,
        "iotc_initialize_name": None,
        "session_id_allocated": False,
        "iotc_connect_attempted": False,
        "iotc_connect_code": None,
        "iotc_connect_name": None,
        "iotc_connect_timed_out": False,
        "iotc_connect_stop_code": None,
        "iotc_connected": False,
        "rdt_initialize_code": None,
        "rdt_initialize_name": None,
        "rdt_create_attempted": False,
        "rdt_create_code": None,
        "rdt_create_name": None,
        "rdt_connected": False,
        "passive_read_attempted": False,
        "passive_read_count": 0,
        "passive_read_bytes": 0,
        "passive_read_last_code": None,
        "cleanup": {},
        "safety": {
            "rdt_write_bound": False,
            "rdt_write_called": False,
            "application_payload_written": False,
            "gate_command_sent": False,
        },
    }


def _run_transport_probe(lib: ctypes.CDLL, uid: str, out: dict[str, Any]) -> None:
    """Populate one report using only connect/create/passive-read operations."""
    lib.IOTC_Initialize2.argtypes = [ctypes.c_ushort]
    lib.IOTC_Initialize2.restype = ctypes.c_int
    lib.IOTC_Get_SessionID.argtypes = []
    lib.IOTC_Get_SessionID.restype = ctypes.c_int
    lib.IOTC_Connect_ByUID_Parallel.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.IOTC_Connect_ByUID_Parallel.restype = ctypes.c_int
    lib.IOTC_Session_Close.argtypes = [ctypes.c_int]
    lib.IOTC_Session_Close.restype = ctypes.c_int
    lib.IOTC_DeInitialize.argtypes = []
    lib.IOTC_DeInitialize.restype = ctypes.c_int

    sid: int | None = None
    rdt_id: int | None = None
    iotc_initialized = False
    rdt_initialized = False
    try:
        init = int(lib.IOTC_Initialize2(0))
        out["iotc_initialize_code"] = init
        out["iotc_initialize_name"] = _error_name(init, IOTC_ERRORS)
        if init not in (0, -3):
            return
        iotc_initialized = True

        sid = int(lib.IOTC_Get_SessionID())
        if sid < 0:
            out["iotc_connect_code"] = sid
            out["iotc_connect_name"] = _error_name(sid, IOTC_ERRORS)
            return
        out["session_id_allocated"] = True

        out["iotc_connect_attempted"] = True
        connect_code, timed_out, stop_code = _connect(lib, uid, sid, 25.0)
        out["iotc_connect_code"] = connect_code
        out["iotc_connect_name"] = _error_name(connect_code, IOTC_ERRORS)
        out["iotc_connect_timed_out"] = timed_out
        out["iotc_connect_stop_code"] = stop_code
        if connect_code is None or connect_code < 0:
            return
        out["iotc_connected"] = True

        if not all(out["symbols"].get(name) for name in RDT_SYMBOLS):
            return

        lib.RDT_Initialize.argtypes = []
        lib.RDT_Initialize.restype = ctypes.c_int
        lib.RDT_Create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_ubyte]
        lib.RDT_Create.restype = ctypes.c_int
        lib.RDT_Read.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.RDT_Read.restype = ctypes.c_int
        lib.RDT_Destroy.argtypes = [ctypes.c_int]
        lib.RDT_Destroy.restype = ctypes.c_int
        lib.RDT_DeInitialize.argtypes = []
        lib.RDT_DeInitialize.restype = ctypes.c_int

        rdt_init = int(lib.RDT_Initialize())
        out["rdt_initialize_code"] = rdt_init
        out["rdt_initialize_name"] = _error_name(rdt_init, RDT_ERRORS)
        if rdt_init <= 0 and rdt_init != -10001:
            return
        rdt_initialized = True

        out["rdt_create_attempted"] = True
        rdt_id = int(lib.RDT_Create(sid, 10000, 0))
        out["rdt_create_code"] = rdt_id
        out["rdt_create_name"] = _error_name(rdt_id, RDT_ERRORS)
        if rdt_id < 0:
            return
        out["rdt_connected"] = True

        # Passive receive only. No RDT_Write symbol is bound anywhere in this file.
        out["passive_read_attempted"] = True
        buf = ctypes.create_string_buffer(4096)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            ret = int(lib.RDT_Read(rdt_id, buf, len(buf), 300))
            out["passive_read_last_code"] = ret
            if ret > 0:
                out["passive_read_count"] += 1
                out["passive_read_bytes"] += ret
            elif ret < 0 and ret != -10007:
                break
    finally:
        cleanup = out["cleanup"]
        if rdt_id is not None and rdt_id >= 0 and out["symbols"].get("RDT_Destroy"):
            try:
                cleanup["rdt_destroy_code"] = int(lib.RDT_Destroy(rdt_id))
            except Exception as err:
                cleanup["rdt_destroy_error"] = type(err).__name__
        if sid is not None and sid >= 0:
            try:
                cleanup["iotc_session_close_code"] = int(lib.IOTC_Session_Close(sid))
            except Exception as err:
                cleanup["iotc_session_close_error"] = type(err).__name__
        if rdt_initialized and out["symbols"].get("RDT_DeInitialize"):
            try:
                cleanup["rdt_deinitialize_code"] = int(lib.RDT_DeInitialize())
            except Exception as err:
                cleanup["rdt_deinitialize_error"] = type(err).__name__
        if iotc_initialized:
            try:
                cleanup["iotc_deinitialize_code"] = int(lib.IOTC_DeInitialize())
            except Exception as err:
                cleanup["iotc_deinitialize_error"] = type(err).__name__


def main() -> int:
    out = _new_report()
    if len(sys.argv) != 2:
        out["library_error"] = "expected one library path"
        print(json.dumps(out, sort_keys=True))
        return 2

    uid = sys.stdin.readline().strip()
    if len(uid) != 20 or not uid.isascii():
        out["library_error"] = "invalid 20-character ASCII OURANOS UID"
        print(json.dumps(out, sort_keys=True))
        return 2

    path = Path(sys.argv[1])
    try:
        lib = ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
    except OSError as err:
        out["library_error"] = f"{type(err).__name__}:{err}"
        print(json.dumps(out, sort_keys=True))
        return 0
    out["library_loaded"] = True

    all_symbols = REQUIRED_IOTC + RDT_SYMBOLS + (
        "IOTC_Connect_Stop_BySID",
        "TUTK_SDK_Set_License_Key",
    )
    out["symbols"] = {name: hasattr(lib, name) for name in all_symbols}
    if not all(out["symbols"][name] for name in REQUIRED_IOTC):
        out["library_error"] = "required_iotc_symbols_missing"
        print(json.dumps(out, sort_keys=True))
        return 0

    _run_transport_probe(lib, uid, out)
    # Print only after cleanup, so Home Assistant receives the final report.
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
