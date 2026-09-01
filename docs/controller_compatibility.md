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


## Per-model optional capability matrix

The effective Android visibility methods were resolved through each concrete
controller's full inheritance chain in both apps:

- `pedBtnVisible()`
- `extDevBtnVisible()`
- `lightBtnVisible()`

Android `View.VISIBLE` is value `0`; `View.GONE` is value `8`. The
effective result is identical between TMT Chow 3.1.4 and gatePRO Smart! 1.0.0
for all 217 gate-controller classes.

| Family | Models | Pedestrian visible | External visible | Light visible |
| --- | ---: | ---: | ---: | ---: |
| Sliding | 88 | 69 | 47 | 5 |
| Swing | 75 | 72 | 14 | 6 |
| Garage | 54 | 35 | 51 | 52 |
| **Total** | **217** | **176** | **112** | **63** |

The exact model sets are stored in `controller_types.py` as
`PEDESTRIAN_CONTROLLERS`, `EXTERNAL_CONTROLLERS` and
`LIGHT_CONTROLLERS`. PS21053C is treated as the runtime alias of PS21053 and
inherits the same optional capabilities.

For PS21053/PS21053C the extracted capability set is:
`pedestrian`, `external`; light is hidden.

Unknown/new model names intentionally receive no optional capability merely
from their family or product_type. This avoids exposing a control that the
vendor app itself would hide.


## Per-model parameter schemas

The Android `PkParameter` constructors were resolved for every concrete gate
controller class, including inherited definitions. The TMT Chow 3.1.4 APK and
gatePRO Smart! 1.0.0 XAPK produce the same logical parameter matrix for all
217 gate-controller models.

Extracted coverage:
- 217 gate models with parameter definitions
- 170 unique ordered parameter schemas
- 856 unique parameter specifications after deduplication
- schema sizes range from 4 to 38 UI parameters
- option, numeric, bit and bitfield parameter constructors are represented
- parameter names, option-list resource keys, English option values, defaults,
  levels, offsets, range limits, increments, multipliers, units and bit metadata
  are retained where present in the vendor apps

The generated data lives in
`custom_components/tmt_chow/model_parameter_schemas.py`. Runtime diagnostics
now include the exact schema selected for the detected `device_type`.

The vendor UART packing/encoding rules have now also been implemented per
model. The implementation carries each concrete model's UART generation,
skip-list, codec profile and any extended suffix from the Android logic, then
performs a mandatory read-back verification after every write.

All 217 concrete gate-controller models therefore have a model-specific read
and write codec. PS21053/PS21053C retain their existing 17-value entity IDs and
wire format for backward compatibility. Unknown/API-only models such as
PS25007 remain read/write disabled until a concrete vendor schema and codec are
available, rather than borrowing another controller's layout.


## Per-model parameter matrix

The controller map now includes the vendor parameter list for every one of the
217 APK-visible gate controller models, plus the PS21053C runtime alias.

The extracted catalogue contains:
- 217 concrete gate models
- 170 distinct parameter layouts after deduplication
- 128 distinct parameter labels
- 297 distinct vendor option lists

Each model entry records the parameter order used by that controller, the
vendor parameter/resource key, English vendor label and the exact option list
when the parameter is discrete. Numeric/packed parameters are retained as
non-discrete entries instead of being incorrectly converted to PS21053-style
selects.

The runtime diagnostics now report the selected model's schema id, parameter
count, ordered parameter schema and effective parameter codec group.

### Codec safety

Parameter layout and parameter wire codec are separate. The 217 mapped gate
models resolve to 9 effective wire-codec profiles:

- legacy_base: 177 models
- new_phase1: 17 models
- custom_a510: 8 models
- custom_p170: 4 models
- converted_swap_8_9: 3 models
- converted_bits: 3 models
- custom_p100: 2 models
- custom_split_pair: 2 models
- custom_csv6: 1 model

All 217 profiles now have explicit read/write encoding logic. Unknown/API-only
models are still excluded from parameter writes until a concrete vendor model
schema and protocol profile are available.


## Home Assistant parameter entities

Discrete vendor parameters are exposed as `select` entities and numeric
vendor parameters with explicit min/max metadata are exposed as `number`
entities. Non-editable information/action rows from the Android parameter list
are not exposed as writable entities.

The integration always reads the full current parameter vector before a
change, modifies only the requested logical parameter, encodes the complete
model-specific vendor payload, sends it once, and reads the parameters back.
The write is accepted only if the requested value is confirmed by the
controller.
