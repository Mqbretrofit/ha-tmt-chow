# PS21050D / PS21050 vendor-app parameter mapping

This mapping was extracted directly from **TMT Chow 3.1.4** (`TMT+Chow!_V3.1.4_APKPure.apk`) and checked against a real controller diagnostic.

## Identity alias

The Android app contains the product implementation `tw.timotion.product.swing.PS21050`. There is no separate `PS21050D` product implementation/string in the app DEX files.

For the tested hardware:

- TMT account/API model: `PS21050`
- live `DEV INFO`: `P190U,PS21050D,V01`
- live `DEV PARAM`: 20 values
- live `ACK RP,1`: the same 20 values

The integration therefore preserves the concrete live identity `PS21050D`, while using the official app's `PS21050` family and UI capabilities for this exact alias pair.

## Wire protocol

`PS21050` sets the vendor product protocol selector `mUartVersion = 1`, which selects:

- read: `RP,1`
- read acknowledgement: `ACK RP,1`
- write: `WP,1:<20 comma-separated values>`
- write acknowledgement: `ACK WP`

The Shadow field `UART VER` reported by the tested WBT/controller path is `2`. That runtime field is separate controller metadata and is not the Android product-class protocol selector.

## Why the generated PS21050 schema has 24 entries

The APK extraction contains 24 logical PS21050 definitions. The first four are helper definitions for the two overcurrent fields:

1. opening overcurrent, normal table (`2 A` to `5 A`)
2. closing overcurrent, normal table (`2 A` to `5 A`)
3. opening overcurrent, Hall table (`0.5 A` to `4.0 A`, wire offset `5`)
4. closing overcurrent, Hall table (`0.5 A` to `4.0 A`, wire offset `5`)

The following contiguous 20 definitions are the actual `RP,1` / `WP,1` wire frame. The final integration does **not** feed all 24 definitions to the generic codec. It extracts the exact 20-field suffix and uses the first four definitions only as the vendor's mode-dependent option/offset helpers for the opening/closing current fields.

## Exact 20-value wire layout

| # | APK key | Vendor UI label | Options |
|---:|---|---|---|
| 1 | `func_system_learn_method` | Motor Type | Overcurrent; Limit Switch; Hall Sensor |
| 2 | `func_open_over_current` | Overcurrent for Gate Opening | normal: 2 A; 3 A; 4 A; 5 A / Hall: 0.5 A to 4.0 A |
| 3 | `func_close_over_current` | Overcurrent for Gate Closing | normal: 2 A; 3 A; 4 A; 5 A / Hall: 0.5 A to 4.0 A |
| 4 | `func_open_speed` | Motor Speed for Opening | 40%; 50%; 75%; 100% |
| 5 | `func_close_speed` | Motor Speed for Closing | 40%; 50%; 75%; 100% |
| 6 | `function_slow_speed_setting` | Deceleration Speed | 40%; 50%; 60%; 70% |
| 7 | `func_slow_down_point` | Deceleration Point | 75%; 80%; 85%; 90%; 95% |
| 8 | `func_open_delay` | Time Gap b/w Two Gates (Opening) | 0; 2; 5; 10; 15; 20; 25; 35; 45; 55 sec |
| 9 | `func_close_delay` | Time Gap b/w Two Gates (Closing) | 0; 2; 5; 10; 15; 20; 25; 35; 45; 55 sec |
| 10 | `func_auto_closing` | Auto-closing | OFF; 3; 10; 20; 40; 60; 120; 180; 300 sec |
| 11 | `func_photocell` | Safety Device Function Mode | Mode 1; Mode 2; Mode 3; Mode 4; Mode 5; Mode 6; Mode 7 |
| 12 | `func_pedestrian_mode` | Pedestrian Mode | OFF; ON |
| 13 | `function_alert_light` | Flashing Light | OFF; ON |
| 14 | `func_ph1` | Photocell Activation | OFF; ON |
| 15 | `func_ph2` | Photocell 2 Activation | OFF; ON |
| 16 | `func_alarm_buzzer` | Alarm Buzzer | OFF; ON |
| 17 | `func_electronic_locker` | Electric Latch Mode | Standard Gate Opening; Release Gate Tension before Opening (gate reversing for 0.25 s) |
| 18 | `func_led_direction` | LED Direction | terminal block at top; terminal block at bottom |
| 19 | `func_single_door` | Dual / Single Gate | Single Gate; Dual Gate |
| 20 | `func_close_limit_reaction_time` | Overcurrent Reverses Time when Close | OFF; 0.1; 0.2; 0.3; 0.4; 0.5; 0.6 sec |

## Real-hardware capture

The verified 20-value frame was:

```text
0,1,1,2,2,1,3,1,2,0,0,1,0,1,0,1,0,1,1,0
```

Decoded with the app's exact option tables:

1. Motor Type: Overcurrent
2. Opening overcurrent: 3 A
3. Closing overcurrent: 3 A
4. Opening speed: 75%
5. Closing speed: 75%
6. Deceleration speed: 50%
7. Deceleration point: 90%
8. Opening gate delay: 2 sec
9. Closing gate delay: 5 sec
10. Auto-closing: OFF
11. Safety Device Function Mode: Mode 1
12. Pedestrian Mode: ON
13. Flashing Light: OFF
14. Photocell Activation: ON
15. Photocell 2 Activation: OFF
16. Alarm Buzzer: ON
17. Electric Latch Mode: Standard Gate Opening
18. LED Direction: terminal block at bottom
19. Dual / Single Gate: Dual Gate
20. Close-overcurrent reversal time: OFF

## Write safety

The integration writes the same complete 20-value `WP,1` frame used by the vendor app. Before every write it reads a fresh `RP,1` frame, changes exactly one requested field, validates all 20 values against the active vendor option tables, sends **one** `WP,1`, then reads `RP,1` again and verifies the requested raw value. A timeout never causes an automatic write retry.

The current option tables depend on Motor Type. Hall mode uses the APK's Hall-current helper table and its wire offset. A Motor Type change is rejected before `WP,1` if the existing current values would be invalid in the target mode; the integration does not guess or silently rewrite the two current settings.

No live parameter write was sent while deriving this mapping. The protocol, field order, options and offsets come from the vendor app; the real controller capture verifies the 20-value read frame.
