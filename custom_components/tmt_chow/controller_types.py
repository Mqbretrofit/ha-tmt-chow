"""Controller-family mapping extracted from TMT Chow Android 3.1.4.

The Android app contains separate product implementations for sliding, swing,
garage, tube-motor and accessory devices.  This table is intentionally based
on the controller/device type string (for example PS21053), not product_type:
the cloud API can return the same product_type value for different device
types.

Only PS21053/PS21053C currently have a verified 17-value parameter schema in
this Home Assistant integration.  Family recognition must therefore never be
used as permission to write that parameter schema to another controller.
"""

from __future__ import annotations

from typing import Final

FAMILY_SLIDING: Final = "sliding"
FAMILY_SWING: Final = "swing"
FAMILY_GARAGE: Final = "garage"
FAMILY_TUBEMOTOR: Final = "tubemotor"
FAMILY_ACCESSORIES: Final = "accessories"
FAMILY_IPCAM: Final = "ipcam"

SLIDING_CONTROLLERS: Final = frozenset({
    "A510", "A520U", "P500BH", "P520U", "P550SA", "P600H",
    "PS17004", "PS17048", "PS17066", "PS17079", "PS17089",
    "PS18004", "PS18005", "PS18013", "PS18015", "PS18020", "PS18028",
    "PS18030", "PS18038", "PS18040", "PS18050", "PS18052", "PS18084",
    "PS18085", "PS18091", "PS18100",
    "PS19013", "PS19014", "PS19027", "PS19029", "PS19030", "PS19033",
    "PS19038", "PS19044", "PS19056", "PS19073", "PS19074", "PS19089",
    "PS19091", "PS19100",
    "PS20003", "PS20004", "PS20009", "PS20010", "PS20033", "PS20037",
    "PS20040", "PS20043", "PS20060", "PS20076",
    "PS20106", "PS20108", "PS20111", "PS20112", "PS20119", "PS20133",
    "PS20135",
    "PS21014", "PS21017", "PS21018", "PS21021", "PS21039", "PS21042",
    "PS21052", "PS21053", "PS21053C", "PS21061", "PS21064", "PS21065",
    "PS21071", "PS21078",
    "PS22005", "PS22006", "PS22022", "PS22028", "PS22055", "PS22060",
    "PS22061", "PS22065", "PS22070", "PS22091",
    "PS22110", "PS22111",
    "PS23001", "PS23004", "PS23009", "PS23010", "PS23016",
    "PS25094",
})

SWING_CONTROLLERS: Final = frozenset({
    "A300", "P100", "P102U", "P170", "P172", "P190U",
    "PS17062", "PS17080", "PS17092",
    "PS18001", "PS18002", "PS18014", "PS18055", "PS18074", "PS18077",
    "PS18090", "PS18092", "PS18107",
    "PS19001", "PS19011", "PS19016", "PS19040", "PS19041", "PS19062",
    "PS19075", "PS19092", "PS19093", "PS19101", "PS19102",
    "PS20005", "PS20006", "PS20007", "PS20061", "PS20088", "PS20096",
    "PS20098", "PS20109", "PS20113", "PS20125",
    "PS21004", "PS21011", "PS21047", "PS21049", "PS21050", "PS21051",
    "PS21068", "PS21080", "PS21084",
    "PS22021", "PS22027", "PS22043", "PS22045", "PS22048", "PS22049",
    "PS22056", "PS22064", "PS22077", "PS22078", "PS22079", "PS22095",
    "PS22101",
    "PS23002", "PS23005", "PS23011", "PS23013", "PS23015", "PS23017",
    "PS23018", "PS23024", "PS23025", "PS23065", "PS23075",
    "PS25061", "PS25065", "PS25076",
})

GARAGE_CONTROLLERS: Final = frozenset({
    "NP14039", "NP19018", "NP20033",
    "P710", "P710U", "P710W", "P720U", "P801U", "P890U",
    "PS16096", "PS17055", "PS17088",
    "PS18011", "PS18012", "PS18049", "PS18061",
    "PS19037", "PS19042", "PS19046", "PS19052", "PS19054", "PS19071",
    "PS19076",
    "PS20002", "PS20025", "PS20038", "PS20063", "PS20130", "PS20141",
    "PS21002", "PS21010", "PS21025", "PS21030", "PS21031", "PS21037",
    "PS21040", "PS21041", "PS21060", "PS21076", "PS21081",
    "PS22008", "PS22009", "PS22034", "PS22038", "PS22074", "PS22085",
    "PS22087", "PS22088",
    "PS23003", "PS23006", "PS23026", "PS23047", "PS23054",
    "PS25078",
})

TUBEMOTOR_CONTROLLERS: Final = frozenset({"AOK1"})

IPCAM_CONTROLLERS: Final = frozenset({
    "BULLET1", "DOME1", "DOME2", "HC1", "ICI1", "ICO1", "ICO3",
    "SC1", "SC3", "TCB1", "TCB2", "TUYA", "TUYABELL",
})

ACCESSORY_CONTROLLERS: Final = frozenset({
    "CHOWHUB", "LEDLIGHT", "RELAYSTRIGGER",
    "NP18043", "NP19023", "PS19031", "PS20027", "PS20052", "PS20059",
    "PS20101", "PS20142", "PS21008", "PS21016", "PS21034", "PS21048",
})

CONTROLLER_FAMILIES: Final = {
    FAMILY_SLIDING: SLIDING_CONTROLLERS,
    FAMILY_SWING: SWING_CONTROLLERS,
    FAMILY_GARAGE: GARAGE_CONTROLLERS,
    FAMILY_TUBEMOTOR: TUBEMOTOR_CONTROLLERS,
    FAMILY_ACCESSORIES: ACCESSORY_CONTROLLERS,
    FAMILY_IPCAM: IPCAM_CONTROLLERS,
}

GATE_FAMILIES: Final = frozenset({
    FAMILY_SLIDING,
    FAMILY_SWING,
    FAMILY_GARAGE,
})

# Product type is cloud metadata and is deliberately NOT used to select a
# controller family.  We have observed both 112 and 118 in the supported app
# ecosystem, and future values must remain accepted without code changes.
OBSERVED_PRODUCT_TYPES: Final = frozenset({"112", "118"})

VERIFIED_PARAMETER_CONTROLLERS: Final = frozenset({
    "PS21053",
    "PS21053C",
})


def normalize_controller_type(controller_type: str | None) -> str:
    """Return a stable uppercase controller type."""
    return (controller_type or "").strip().upper()


def controller_family(controller_type: str | None) -> str | None:
    """Return the Android-app product family for a controller type."""
    normalized = normalize_controller_type(controller_type)
    if not normalized:
        return None
    for family, controllers in CONTROLLER_FAMILIES.items():
        if normalized in controllers:
            return family
    return None


def is_known_gate_controller(controller_type: str | None) -> bool:
    """Return whether the APK maps this type to a gate family."""
    return controller_family(controller_type) in GATE_FAMILIES


def has_verified_parameter_schema(controller_type: str | None) -> bool:
    """Return whether our 17-value parameter schema is verified for this type."""
    return normalize_controller_type(controller_type) in VERIFIED_PARAMETER_CONTROLLERS
