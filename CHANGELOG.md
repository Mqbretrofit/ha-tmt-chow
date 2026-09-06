# Changelog

## v1.0.3-beta.1

- Added model-gated pedestrian / partial opening control using the verified `PED OPEN` command
- Fixed a stale `DEV STATUS` stop-position update that could make a fully closed gate jump back to `open`
- Added ACK-loss tolerance for open/close/pedestrian movement commands when fresh telemetry proves the requested motion actually started
- Movement commands are never resent when an ACK is missing
- Added direct APK-derived `PS21050D` support by mapping the exact account `PS21050` / live `PS21050D` pair to the official TMT Chow 3.1.4 `PS21050` implementation
- Added the full 20-entry PS21050 parameter schema, names/options and normal `RP,1` / `WP,1` parameter path to live PS21050D hardware
- Added the PS21050 pedestrian capability to the live PS21050D alias through the vendor app profile
- Corrected the distinction between the Android product protocol selector (`mUartVersion = 1`) and the live Shadow `UART VER = 2` metadata
- Added `PS21050D_APK_MAPPING.md` documenting the complete vendor-app mapping and decoded real-hardware frame
- Extended diagnostics with configured/live/parameter-model and write-verification state
- Added regression tests for stale stop positions, ACK-loss handling, pedestrian command selection, and the APK-derived PS21050D alias/read/write protocol

## v1.0.1

- Fixed missing Home Assistant integration brand assets in the published release
- Added the local `brand/` folder to the installable package
- Includes `icon.png`, `icon@2x.png`, `dark_icon.png` and `dark_icon@2x.png`
- No functional changes to gate control or controller parameters

## v1.0.0

- First stable release
- Gate open / close / stop control
- Live gate state and position
- Battery monitoring
- ChowHUB controller parameter configuration
- Home Assistant Config Flow
- Diagnostics support
- 23 interface translations
