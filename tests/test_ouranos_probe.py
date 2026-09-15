"""Regression tests for the standalone read-only OURANOS/TUTK probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROBE_PATH = Path(__file__).parents[1] / "tools" / "tmt_chow_ouranos_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("tmt_chow_ouranos_probe", PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ouranos_probe_offline_self_test() -> None:
    probe = _load_probe()
    probe._self_test()


def test_ouranos_probe_selects_only_uuid_type_one() -> None:
    probe = _load_probe()
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

    candidates = probe._device_candidates(payload)

    assert len(candidates) == 1
    assert candidates[0]["uuid_type"] == "1"
    assert candidates[0]["device_type"] == "PS19001"
    assert candidates[0]["product_type"] == "108"


def test_ouranos_probe_has_no_rdt_write_binding() -> None:
    source = PROBE_PATH.read_text(encoding="utf-8")

    # Comments/help text may name RDT_Write while explaining the safety rule,
    # but the ctypes binding/call syntax must never exist in probe v0.1.
    assert ".RDT_Write(" not in source
    assert ".RDT_Write.argtypes" not in source
    assert ".RDT_Write.restype" not in source
