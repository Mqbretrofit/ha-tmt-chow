# TMT Chow v1.0.3-beta.1

Beta release for live testing before the next stable version.

## Added

- Pedestrian / partial gate opening through the vendor `PED OPEN` MQTT command.
- A dedicated Home Assistant **Pedestrian opening** button.
- The button is created only for controller models whose pedestrian control is exposed by the TMT Chow / gatePRO app capability matrix.
- `PS21053C` has been verified on real hardware with `ACK PED OPEN` and a partial position update.
- Safe controller-variant parameter probing when live `DEV INFO` differs from the model returned by the TMT account API.
- Direct APK-derived `PS21050D` support: TMT Chow 3.1.4 has no separate `PS21050D` implementation and uses its `PS21050` swing-gate product class/profile. The integration preserves the live `PS21050D` identity while applying that official `PS21050` family, capabilities and 20-parameter schema for the exact account-model/live-model alias pair.
- All 20 `PS21050` parameters, names and option arrays were extracted from the vendor app and are now available through the normal model-specific Home Assistant parameter entities on `PS21050D` hardware.
- `PS21050D` gains the vendor-app pedestrian capability because the `PS21050` implementation exposes its pedestrian button.
- Added `PS21050D_APK_MAPPING.md` with the full 20-entry app mapping and the decoded real-hardware capture.
- Diagnostics report configured/live controller type, selected parameter model/source and parameter protocol metadata.

## Fixed

- Prevent a stale `DEV STATUS` position from contradicting the direction of the movement that just completed. This addresses issue #5 where a physically closed gate could jump back to `open` in Home Assistant.
- If an `ACK FULL OPEN`, `ACK FULL CLOSE`, or `ACK PED OPEN` is lost, Home Assistant now accepts the command as successful only when fresh post-command telemetry proves that the requested movement actually started.
- A missing ACK never causes the movement command to be resent.
- Avoid losing a model-specific parameter read when the live `DEV INFO` updates the controller variant while the initial parameter request is still in flight.
- Corrected the `PS21050D` protocol interpretation: the app's `mUartVersion = 1` selects the `RP,1` / `WP,1` protocol. The separately reported Shadow `UART VER = 2` is runtime controller metadata and is not the Android product protocol selector.

## PS21050D hardware validation

A real controller reports:

- account/API model: `PS21050`
- live `DEV INFO`: `P190U,PS21050D,V01`
- live `DEV PARAM`: 20 values
- `ACK RP,1`: the same 20 values

TMT Chow 3.1.4 contains `tw.timotion.product.swing.PS21050` and no separate `PS21050D` product implementation/string. The app's final `PS21050.mParameters` wire array contains exactly 20 fields, matching the real `RP,1` frame. The normal APK-derived `PS21050` codec therefore supplies the `RP,1` read and `WP,1:<20 CSV values>` write layout for this exact alias.

No live parameter write was sent while reverse-engineering this mapping. Parameter writes are only triggered by an explicit Home Assistant entity change and still use the integration's read-before-write plus read-back verification path.

## Notes

This is a beta build. `PS21053C` pedestrian opening and `PS21050D` parameter reading are both backed by real-hardware captures. The `PS21050D` parameter names/options and write layout come directly from TMT Chow 3.1.4 rather than manual trial-and-error mapping.
