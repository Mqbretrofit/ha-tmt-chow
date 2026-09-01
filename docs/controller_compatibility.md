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
