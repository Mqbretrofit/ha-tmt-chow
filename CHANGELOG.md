# Changelog

## v1.0.3-beta.1

- Added model-gated pedestrian / partial opening control using the verified `PED OPEN` command
- Fixed a stale `DEV STATUS` stop-position update that could make a fully closed gate jump back to `open`
- Added ACK-loss tolerance for open/close/pedestrian movement commands when fresh telemetry proves the requested motion actually started
- Movement commands are never resent when an ACK is missing
- Added regression tests for stale stop positions, ACK-loss handling, and pedestrian command selection

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
