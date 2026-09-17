"""Regression tests for the Home Assistant-hosted OURANOS transport probe."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import textwrap
import types
from pathlib import Path

ROOT = Path(__file__).parents[1]
PROBE_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_ha_probe.py"
HELPER_PATH = ROOT / "custom_components" / "tmt_chow" / "ouranos_native_helper.py"
GLIBC_HELPER_PATH = (
    ROOT / "custom_components" / "tmt_chow" / "native" / "ouranos_glibc_helper.amd64"
)
GLIBC_HELPER_SHA_PATH = GLIBC_HELPER_PATH.with_suffix(".amd64.sha256")
GLIBC_HELPER_SOURCE = ROOT / "tools" / "ouranos_glibc_helper.c"
SESSION_HELPER_PATH = (
    ROOT / "custom_components" / "tmt_chow" / "native"
    / "ouranos_glibc_session_helper.amd64"
)
SESSION_HELPER_SHA_PATH = SESSION_HELPER_PATH.with_suffix(".amd64.sha256")
SESSION_HELPER_SOURCE = ROOT / "tools" / "ouranos_glibc_session_helper.c"
INIT_PATH = ROOT / "custom_components" / "tmt_chow" / "__init__.py"


def _load_probe():
    try:
        __import__("homeassistant.core")
    except ModuleNotFoundError:
        homeassistant = types.ModuleType("homeassistant")
        core = types.ModuleType("homeassistant.core")
        helpers = types.ModuleType("homeassistant.helpers")
        aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
        core.HomeAssistant = object
        aiohttp_client.async_get_clientsession = lambda hass: None
        sys.modules.setdefault("homeassistant", homeassistant)
        sys.modules.setdefault("homeassistant.core", core)
        sys.modules.setdefault("homeassistant.helpers", helpers)
        sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    spec = importlib.util.spec_from_file_location("tmt_chow_ouranos_ha_probe", PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_home_assistant_probe_uses_pinned_tmt_generation_x64_sdk() -> None:
    probe = _load_probe()
    assert probe._SUPPORTED_MACHINES == frozenset({"x86_64", "amd64"})
    assert probe._TUTK_SDK_REPOSITORY == "Soldier-Sen/tutk"
    assert probe._TUTK_SDK_COMMIT == "8a93626da7c12c936d550750e887a020c3049dc0"
    assert probe._TUTK_SDK_PATH == "Lib/Linux/x64/tmp_so"
    assert probe._TUTK_LIBRARY_FILES == {
        "iotc": (
            "libIOTCAPIs.so",
            "bf92a8f33f6a69f9c40f5d1a825e993763bc614a0e364112d325e32ec01de843",
        ),
        "rdt": (
            "libRDTAPIs.so",
            "739575ad864b0e76c7fe89546e55e08e5ff8e63c36a95e08e5e744a607362296",
        ),
    }
    assert probe._TMT_APK_IOTC_VERSION == "0x03010521"
    assert probe._PROBE_IOTC_VERSION == "0x03010526"
    assert probe._PROBE_RDT_VERSION == "0x03010526"


def test_twenty_character_uid_is_accepted_by_transport_probe() -> None:
    probe = _load_probe()
    result = probe._base_result("ABCDEFGHIJKLMNOPQRST")
    assert result["applicable"] is True
    assert result["safety"]["rdt_write_called"] is False
    assert result["safety"]["gate_command_sent"] is False
    assert result["safety"]["status_read_command_sent"] is False
    assert result["safety"]["parameter_read_command_sent"] is False
    assert result["safety"]["parameter_write_command_sent"] is False


def test_ha_action_requires_confirmed_ps19001_candidate() -> None:
    source = INIT_PATH.read_text(encoding="utf-8")
    assert 'hub.configured_controller_type == "PS19001"' in source
    assert "_is_known_ouranos_candidate(candidate)" in source
    assert "Selected gate is not a confirmed PS19001 OURANOS candidate" in source


def test_private_glibc_runtime_is_pinned() -> None:
    probe = _load_probe()
    assert probe._GLIBC_VERSION == "2.35-0"
    assert probe._GLIBC_URL.endswith("/2.35-0/glibc-bin-2.35-0-x86_64.tar.gz")
    assert probe._MAX_GLIBC_BUNDLE_BYTES == 64 * 1024 * 1024
    assert probe._MAX_GLIBC_BUNDLE_BYTES > 52_484_557
    assert probe._GLIBC_SHA512 == (
        "0aff0ec76f4d341957a792b8635c0770148eba9a5cb64f9bbd85228c14d9cb93"
        "c1a402063cab533a9f536f5f7be92c27bc5be8ed13c2b4f7aa416510c754d071"
    )


def test_ci_built_glibc_helper_hash_matches_probe() -> None:
    probe = _load_probe()
    assert GLIBC_HELPER_PATH.is_file()
    digest = hashlib.sha256(GLIBC_HELPER_PATH.read_bytes()).hexdigest()
    assert digest == probe._GLIBC_HELPER_SHA256
    assert GLIBC_HELPER_SHA_PATH.read_text(encoding="ascii").strip() == digest


def test_safe_glibc_bundle_extracts_only_private_runtime(tmp_path: Path) -> None:
    probe = _load_probe()
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        for name, data in (
            ("usr/glibc-compat/lib/ld-linux-x86-64.so.2", b"loader"),
            ("usr/glibc-compat/lib/libc.so.6", b"libc"),
            ("etc/should-not-be-extracted", b"nope"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))

    target = tmp_path / "glibc"
    probe._safe_extract_glibc_bundle(archive_buffer.getvalue(), target)

    assert (target / "usr/glibc-compat/lib/ld-linux-x86-64.so.2").read_bytes() == b"loader"
    assert (target / "usr/glibc-compat/lib/libc.so.6").read_bytes() == b"libc"
    assert not (target / "etc/should-not-be-extracted").exists()


def test_safe_tutk_install_writes_only_pinned_libraries(
    tmp_path: Path, monkeypatch
) -> None:
    probe = _load_probe()
    iotc = b"iotc-library"
    rdt = b"rdt-library"
    files = {
        "iotc": ("libIOTCAPIs.so", hashlib.sha256(iotc).hexdigest()),
        "rdt": ("libRDTAPIs.so", hashlib.sha256(rdt).hexdigest()),
    }
    monkeypatch.setattr(probe, "_TUTK_LIBRARY_FILES", files)

    target = tmp_path / "tutk"
    probe._safe_install_tutk_libraries({"iotc": iotc, "rdt": rdt}, target)

    assert (target / "libIOTCAPIs.so").read_bytes() == iotc
    assert (target / "libRDTAPIs.so").read_bytes() == rdt
    assert not (target / "should-not-be-extracted").exists()
    assert (target / ".source-commit").read_text(encoding="ascii") == (
        probe._TUTK_SDK_COMMIT
    )


def test_helper_stdout_parser_uses_last_json_object() -> None:
    probe = _load_probe()
    stdout = b"native log line\n{\"old\": true}\nmore native noise\n{\"rdt_connected\": true}\n"
    assert probe._parse_helper_stdout(stdout) == {"rdt_connected": True}


def test_helper_error_redacts_uid() -> None:
    probe = _load_probe()
    uid = "ABCDEFGHIJKLMNOPQRST"
    pin_code = "123456"
    error = probe._safe_helper_error(
        f"failed for UID {uid} with PIN {pin_code}".encode(), uid, pin_code
    )
    assert error == "failed for UID <redacted-uid> with PIN <redacted-pin>"
    assert uid not in error
    assert pin_code not in error


def test_native_helper_has_only_allowlisted_status_write_path() -> None:
    python_source = HELPER_PATH.read_text(encoding="utf-8")
    c_source = GLIBC_HELPER_SOURCE.read_text(encoding="utf-8")

    assert ".RDT_Write(" not in python_source
    assert ".RDT_Write.argtypes" not in python_source
    assert ".RDT_Write.restype" not in python_source
    assert "RDT_Write" in c_source
    assert c_source.count("RDT_Write(rdt_id,request,request_len)") == 1
    assert "READ STATUS;src=P9999999\\\\r\\\\n" in c_source

    for command in (
        "FULL OPEN",
        "FULL CLOSE",
        "PED OPEN",
        "READ FUNCTION",
        "c=RS",
    ):
        assert command not in python_source
        assert command not in c_source

    assert '"gate_command_sent\\\":false' in c_source
    assert '"parameter_read_command_sent\\\":false' in c_source
    assert '"parameter_write_command_sent\\\":false' in c_source
    assert "passive_attempted=1" not in c_source


def test_persistent_helper_has_fixed_status_only_protocol() -> None:
    source = SESSION_HELPER_SOURCE.read_text(encoding="utf-8")
    digest = hashlib.sha256(SESSION_HELPER_PATH.read_bytes()).hexdigest()
    session_module = (
        ROOT / "custom_components/tmt_chow/ouranos_native_session.py"
    ).read_text(encoding="utf-8")

    assert SESSION_HELPER_SHA_PATH.read_text(encoding="ascii").strip() == digest
    assert digest in session_module
    assert source.count("rdt_write(rdt_id, request, request_length)") == 1
    assert 'strcmp(command, "STATUS")' in source
    assert 'strcmp(command, "QUIT")' in source
    assert "READ STATUS;src=P9999999\\\\r\\\\n" in source
    for command in ("FULL OPEN", "FULL CLOSE", "PED OPEN", "READ FUNCTION", "c=RS"):
        assert command not in source


def test_persistent_helper_reuses_connection_for_status_reads(tmp_path: Path) -> None:
    iotc_source = tmp_path / "session_iotc.c"
    rdt_source = tmp_path / "session_rdt.c"
    iotc_library = tmp_path / "libIOTCAPIs.so"
    rdt_library = tmp_path / "libRDTAPIs.so"
    iotc_source.write_text(
        textwrap.dedent(
            """
            int IOTC_Initialize2(unsigned short port) { (void)port; return 0; }
            int IOTC_Get_SessionID(void) { return 7; }
            int IOTC_Connect_ByUID_Parallel(const char *uid, int sid) {
                (void)uid; (void)sid; return 0;
            }
            void IOTC_Session_Close(int sid) { (void)sid; }
            int IOTC_DeInitialize(void) { return 0; }
            int IOTC_Connect_Stop_BySID(int sid) { (void)sid; return 0; }
            """
        ),
        encoding="utf-8",
    )
    rdt_source.write_text(
        textwrap.dedent(
            r'''
            #include <string.h>
            static int wrote = 0;
            static const char pin[] = "123456";
            static const char request[] = "{\"VER\":1,\"CMD\":\"UART\",\"ACT\":\"POST\",\"DATA\":{\"PKCMD\":\"READ STATUS;src=P9999999\\r\\n\"}}";
            static const char response[] = "{\"VER\":1,\"CMD\":\"UART\",\"RESULT\":0,\"DATA\":\"ACK STATUS:CLOSED,0;src=P1234567\"}";
            int RDT_Initialize(void) { return 128; }
            int RDT_Create(int sid, int timeout, unsigned char channel) {
                (void)sid; (void)timeout; (void)channel; return 0;
            }
            int RDT_Write(int id, const char *data, int length) {
                int i; (void)id;
                if (length != (int)strlen(request)) return -10014;
                for (i = 0; i < length; ++i)
                    if ((data[i] ^ pin[i % 6]) != request[i]) return -10014;
                wrote = 1; return length;
            }
            int RDT_Read(int id, char *data, int length, int timeout) {
                int i, size = (int)strlen(response); (void)id; (void)timeout;
                if (!wrote) return -10007;
                if (length < size) return -10014;
                for (i = 0; i < size; ++i) data[i] = response[i] ^ pin[i % 6];
                wrote = 0; return size;
            }
            int RDT_Destroy(int id) { (void)id; return 0; }
            int RDT_DeInitialize(void) { return 0; }
            '''
        ),
        encoding="utf-8",
    )
    for source, output in ((iotc_source, iotc_library), (rdt_source, rdt_library)):
        subprocess.run(
            ["gcc", "-shared", "-fPIC", str(source), "-o", str(output)],
            check=True,
        )

    process = subprocess.Popen(
        [str(SESSION_HELPER_PATH), str(iotc_library), str(rdt_library)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write("ABCDEFGHIJKLMNOPQRST\n123456\n")
    process.stdin.flush()
    assert json.loads(process.stdout.readline())["connected"] is True

    process.stdin.write("OPEN\n")
    process.stdin.flush()
    assert json.loads(process.stdout.readline())["error"] == "unsupported_command"
    responses = []
    for _ in range(2):
        process.stdin.write("STATUS\n")
        process.stdin.flush()
        responses.append(json.loads(process.stdout.readline()))
    process.stdin.write("QUIT\n")
    process.stdin.flush()
    assert process.wait(timeout=10) == 0

    assert all(item["status_response_received"] is True for item in responses)
    assert all("PXXXXXXX" in item["status_response"] for item in responses)
    assert "123456" not in json.dumps(responses)


def test_status_probe_requires_six_digit_pin_and_keeps_options_local() -> None:
    init_source = INIT_PATH.read_text(encoding="utf-8")
    service_source = (ROOT / "custom_components/tmt_chow/services.yaml").read_text(
        encoding="utf-8"
    )

    assert 'call.data.get("pin_code", "")' in init_source
    assert "Gate PIN must contain exactly 6 digits" in init_source
    assert "async_probe_ouranos_on_ha(hass, hub.uuid, pin_code)" in init_source
    assert "type: password" in service_source

    config_flow_source = (
        ROOT / "custom_components/tmt_chow/config_flow.py"
    ).read_text(encoding="utf-8")
    diagnostics_source = (
        ROOT / "custom_components/tmt_chow/diagnostics.py"
    ).read_text(encoding="utf-8")
    assert "TextSelectorType.PASSWORD" in config_flow_source
    assert "CONF_OURANOS_PIN" in diagnostics_source
    assert '"options": async_redact_data(dict(entry.options), _REDACT)' in diagnostics_source


def test_glibc_helper_sends_and_decodes_exact_status_request(tmp_path: Path) -> None:
    iotc_source = tmp_path / "iotc.c"
    rdt_source = tmp_path / "rdt.c"
    iotc_library = tmp_path / "libIOTCAPIs.so"
    rdt_library = tmp_path / "libRDTAPIs.so"

    iotc_source.write_text(
        textwrap.dedent(
            """
            void IOTC_Get_Version(unsigned int *version) { *version = 0x03010526; }
            int IOTC_Initialize2(unsigned short port) { (void)port; return 0; }
            int IOTC_Get_SessionID(void) { return 7; }
            int IOTC_Connect_ByUID_Parallel(const char *uid, int sid) {
                (void)uid; (void)sid; return 0;
            }
            void IOTC_Session_Close(int sid) { (void)sid; }
            int IOTC_DeInitialize(void) { return 0; }
            int IOTC_Connect_Stop_BySID(int sid) { (void)sid; return 0; }
            """
        ),
        encoding="utf-8",
    )
    rdt_source.write_text(
        textwrap.dedent(
            r'''
            #include <string.h>
            static int wrote = 0;
            static const char pin[] = "123456";
            static const char request[] = "{\"VER\":1,\"CMD\":\"UART\",\"ACT\":\"POST\",\"DATA\":{\"PKCMD\":\"READ STATUS;src=P9999999\\r\\n\"}}";
            static const char response[] = "{\"VER\":1,\"CMD\":\"UART\",\"RESULT\":0,\"DATA\":\"ACK STATUS,CLOSE;src=P1234567\"}";
            int RDT_GetRDTApiVer(void) { return 0x03010526; }
            int RDT_Initialize(void) { return 128; }
            int RDT_Create(int sid, int timeout, unsigned char channel) {
                (void)sid; (void)timeout; (void)channel; return 0;
            }
            int RDT_Write(int id, const char *data, int length) {
                int i;
                (void)id;
                if (length != (int)strlen(request)) return -10014;
                for (i = 0; i < length; ++i) {
                    if ((data[i] ^ pin[i % 6]) != request[i]) return -10014;
                }
                wrote = 1;
                return length;
            }
            int RDT_Read(int id, char *data, int length, int timeout) {
                int i, size = (int)strlen(response);
                (void)id; (void)timeout;
                if (!wrote) return -10007;
                if (length < size) return -10014;
                for (i = 0; i < size; ++i) data[i] = response[i] ^ pin[i % 6];
                wrote = 0;
                return size;
            }
            int RDT_Destroy(int id) { (void)id; return 0; }
            int RDT_DeInitialize(void) { return 0; }
            '''
        ),
        encoding="utf-8",
    )
    for source, output in (
        (iotc_source, iotc_library),
        (rdt_source, rdt_library),
    ):
        subprocess.run(
            ["gcc", "-shared", "-fPIC", str(source), "-o", str(output)],
            check=True,
        )

    completed = subprocess.run(
        [str(GLIBC_HELPER_PATH), str(iotc_library), str(rdt_library)],
        input="ABCDEFGHIJKLMNOPQRST\n123456\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    payload = json.loads(completed.stdout)

    assert payload["status_write_code"] > 0
    assert payload["status_request_sent"] is True
    assert payload["status_response_received"] is True
    assert "ACK STATUS,CLOSE;src=PXXXXXXX" in payload["status_response"]
    assert "123456" not in completed.stdout
    assert payload["safety"] == {
        "rdt_write_bound": True,
        "rdt_write_called": True,
        "application_payload_written": True,
        "status_read_command_sent": True,
        "gate_command_sent": False,
        "parameter_read_command_sent": False,
        "parameter_write_command_sent": False,
    }
