# TMT Chow controller compatibility map

Source: controller classes embedded in the TMT Chow Android 3.1.4 APK.

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

The complete model lists live in
`custom_components/tmt_chow/controller_types.py`.

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
