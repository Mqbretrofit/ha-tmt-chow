# PS21050D / PS21050 vendor-app parameter mapping

This mapping was extracted directly from **TMT Chow 3.1.4** (`TMT+Chow!_V3.1.4_APKPure.apk`) and checked against a real controller diagnostic.

## Identity alias

The Android app contains the product implementation `tw.timotion.product.swing.PS21050`. There is no separate `PS21050D` product implementation/string in the app DEX files.

For the tested hardware:

- TMT account/API model: `PS21050`
- live `DEV INFO`: `P190U,PS21050D,V01`
- live `DEV PARAM`: 20 values
- live `ACK RP,1`: the same 20 values

The integration therefore preserves the concrete live identity `PS21050D`, while using the official app's `PS21050` family, capabilities and parameter profile for this exact alias pair.

## Wire protocol

`PS21050` sets the vendor product protocol generation flag `mUartVersion = 1`, which selects:

- read: `RP,1`
- read acknowledgement: `ACK RP,1`
- write: `WP,1:<20 comma-separated values>`
- write acknowledgement: `ACK WP`

The Shadow field `UART VER` reported by the tested WBT/controller path is `2`. That runtime field is not the same value as the Android product-class `mUartVersion` protocol selector.

The constructor creates a 20-entry base `PS21050.mParameters` wire array in this order:

| # | APK key | Vendor UI label | Options |
|---:|---|---|---|
| 1 | `func_system_learn_method` | Motor Type | Overcurrent; Limit Switch; Hall Sensor |
| 2 | `func_open_over_current` | Overcurrent for Gate Opening | 2 A; 3 A; 4 A; 5 A |
| 3 | `func_close_over_current` | Overcurrent for Gate Closing | 2 A; 3 A; 4 A; 5 A |
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
| 18 | `func_led_direction` | LED Direction | Terminal Block at Top; Terminal Block at Bottom |
| 19 | `func_single_door` | Dual / Single Gate | Single Gate; Dual Gate |
| 20 | `func_close_limit_reaction_time` | Overcurrent Reverses Time when Close | OFF; 0.1; 0.2; 0.3; 0.4; 0.5; 0.6 sec |

`PS21050.initParameters()` later appends inherited System Learn/System Config UI entries to the logical parameter list. Those entries do not add fields to this 20-value `RP,1` / `WP,1` frame; the APK-derived codec skips the non-wire parameter types when encoding/decoding.

The constructor also creates alternate opening/closing overcurrent objects for normal/Hall learning modes. Those are helper arrays and likewise do not add extra wire fields.

## Real-hardware capture

The verified 20-value frame was:

```text
0,1,1,2,2,1,3,1,2,0,0,1,0,1,0,1,0,1,1,0
```

Decoded with the app's option arrays, this corresponds to:

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
18. LED Direction: Terminal Block at Bottom
19. Dual / Single Gate: Dual Gate
20. Close-overcurrent reversal time: OFF

No live parameter write was sent while deriving this mapping; the write format comes from the vendor app's PS21050 implementation and the existing APK-derived codec.
