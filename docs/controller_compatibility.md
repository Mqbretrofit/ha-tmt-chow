# TMT Chow controller compatibility map

Sources compared: TMT Chow Android 3.1.4 APK and gatePRO Smart! Android 1.0.0 XAPK. Both contain the same TMT product-controller model families.

The integration identifies hardware primarily by `device_type` / the DEV INFO
controller string. It does **not** use `product_type` as a unique hardware
identifier because cloud responses can reuse one product type value across
different device types.

## APK families

| Family | Models mapped | Home Assistant handling |
| --- | ---: | --- |
| Sliding gate | 88 APK models + PS21053C runtime alias | Gate control enabled |
| Swing gate | 75 | Gate control enabled |
| Garage | 54 | Gate control enabled |
| Tube motor | 1 | Recognized; gate-specific parameter schema is not exposed |
| Accessories | 15 | Recognized; gate-specific parameter schema is not exposed |
| IP camera / doorbell | 13 | Recognized; gate-specific entities are not inferred |

The complete model lists live in `custom_components/tmt_chow/controller_types.py`. This covers 246 APK-visible controller implementations across six families. API devices may still use model names not represented by a concrete APK class; PS25007 is an observed example, so unknown models must not be rejected.

## Parameter safety

The current 17-value `RP,1` / `WP,1` parameter definition was verified for
`PS21053` and `PS21053C` only. Other recognized models are intentionally
not given those selectors until their own parameter layout is verified.

This prevents a controller from receiving a parameter write that was decoded
for another hardware family.

## Unknown/new controllers

An unknown `device_type` is kept usable for the common runtime path and is
reported in diagnostics. It is not automatically assigned to an APK family
and is not allowed to use the PS21053 parameter schema merely because its
`product_type` matches another controller.


## Product types

`product_type` is independent cloud metadata, not a controller-family selector. Known values include at least `112` and `118`, and future values remain accepted. The integration never assumes `112` or `118` identifies a hardware family.


## Gate protocol comparison

The two Android apps use the same shared `PkProduct` gate protocol base for
sliding, swing and garage controllers. The base implements the same primary
commands for all three families:

| Operation | Vendor command | Family result |
| --- | --- | --- |
| Open | `FULL OPEN` | Shared by sliding, swing and garage |
| Close | `FULL CLOSE` | Shared by sliding, swing and garage |
| Stop | `STOP` | Shared by sliding, swing and garage |
| Read gate status | `RS` / `READ STATUS` | Shared base implementation |
| Read parameters | `RP,1` | Shared transport command; parameter layout is model-specific |
| Write parameters | `WP` | Shared transport command; writing is unsafe without a verified model schema |

This is why the Home Assistant cover can safely use the common open/close/stop
transport for known gate families while parameter entities remain restricted
to verified models.

### Optional controls are model-specific

The APK also exposes optional commands such as `PED OPEN`, `EXTERNAL`,
`LIGHT ON`, `LIGHT OFF` and `RELAY4`. Their UI visibility is overridden
by individual controller classes, so family membership alone is not enough to
enable them.

Examples from the APK:
- PS21053: pedestrian and external controls are exposed; light is hidden.
- Garage models frequently expose light control, but individual models can hide it.
- Swing and sliding models vary independently for pedestrian, external and light controls.

These optional commands must therefore be enabled from a per-model capability
map, not by assuming that every controller in one family supports the same UI.

### Status and position

The app uses the common gate-status read path for all three gate families and a
shared gate UI state machine (opening/opened/closing/stopped/closed). Model
classes mainly change product resources, optional-control visibility and
parameter definitions rather than replacing the core open/close/stop protocol.

Known non-gate families (tube motor, accessories and IP camera/doorbell) are
now prevented from being exposed as Home Assistant gate covers. Unknown model
names are still kept on the legacy gate path so API-returned models that are
newer than the APK are not accidentally rejected.
