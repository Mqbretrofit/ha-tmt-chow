# TMT Chow v1.0.3-beta.1

Beta release for live testing before the next stable version.

## Added

- Pedestrian / partial gate opening through the vendor `PED OPEN` MQTT command.
- A dedicated Home Assistant **Pedestrian opening** button.
- The button is created only for controller models whose pedestrian control is exposed by the TMT Chow / gatePRO app capability matrix.
- `PS21053C` has been verified on real hardware with `ACK PED OPEN` and a partial position update.
- Safe controller-variant parameter probing when live `DEV INFO` differs from the model returned by the TMT account API.
- Direct APK-derived `PS21050D` support for the exact account `PS21050` / live `PS21050D` identity pair.
- The final PS21050D implementation uses the exact 20-value `RP,1` / `WP,1` wire layout extracted from TMT Chow 3.1.4, instead of feeding the app's 24 logical PS21050 definitions to the generic codec.
- The four extra PS21050 definitions are handled correctly as normal/Hall overcurrent helper tables; the two current selectors change their option table and wire offset according to Motor Type.
- All 20 wire parameters have vendor-app names/options in Home Assistant on the verified alias.
- `PS21050D` gains the vendor-app pedestrian capability because the `PS21050` implementation exposes pedestrian control.
- Added `PS21050D_APK_MAPPING.md` with the exact 20-field mapping, helper-table explanation and decoded real-hardware capture.
- Added a GitHub Actions test workflow for beta/main regression testing.
- Diagnostics report configured/live controller type, parameter model/source, 20-field codec profile and write-verification state.

## Fixed

- Prevent a stale `DEV STATUS` position from contradicting the direction of the movement that just completed. This addresses issue #5 where a physically closed gate could jump back to `open` in Home Assistant.
- If an `ACK FULL OPEN`, `ACK FULL CLOSE`, or `ACK PED OPEN` is lost, Home Assistant now accepts the command as successful only when fresh post-command telemetry proves that the requested movement actually started.
- A missing ACK never causes the movement command to be resent.
- Avoid losing a model-specific parameter read when the live `DEV INFO` updates the controller variant while the initial parameter request is still in flight.
- Corrected the `PS21050D` protocol interpretation: the app's `mUartVersion = 1` selects the `RP,1` / `WP,1` protocol. The separately reported Shadow `UART VER = 2` is runtime controller metadata and is not the Android product protocol selector.
- Replaced the temporary raw/read-only PS21050D profile with the exact vendor-app mapping only when the TMT account model is `PS21050`; unexpected PS21050D identity combinations remain raw and read-only rather than being guessed.

## PS21050D write safety

Before a PS21050D parameter write, the integration reads a fresh 20-value `RP,1` frame, changes exactly one requested raw field, validates the entire frame against the active vendor option tables, sends one `WP,1`, then reads `RP,1` again and verifies the requested value. Parameter writes are never automatically retried.

Motor Type affects the encoding of the two overcurrent fields. Hall mode uses the APK's Hall-current table and offset. If changing Motor Type would make the existing current values invalid in the target mode, the change is rejected before `WP,1`; the integration does not silently rewrite current settings.

## Hardware validation

A real controller reports account model `PS21050`, live `DEV INFO` model `PS21050D`, and the same 20-value frame through both `DEV PARAM` and `ACK RP,1`. TMT Chow 3.1.4 contains the `tw.timotion.product.swing.PS21050` implementation and no separate PS21050D product implementation/string.

No live parameter write was sent while reverse-engineering this mapping. The protocol, wire order, option tables and offsets come from the vendor app; the real hardware capture verifies the 20-value read frame.

## Notes

This remains a beta build until live testing is complete. `PS21053C` pedestrian opening and `PS21050D` parameter reading are backed by real-hardware captures. The PS21050D parameter mapping is app-derived rather than manually trial-mapped.
