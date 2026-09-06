# Changelog

## v1.0.4-beta.1

- Added a native-style fourth **Pedestrian opening** control directly inside the standard Home Assistant gate more-info popup for controllers with verified pedestrian capability
- The popup button uses the existing verified `PED OPEN` command; it does not misuse Home Assistant tilt semantics
- The existing standalone Pedestrian opening button entity remains available
- Added a small frontend module loaded by the integration and a guarded `tmt_chow.pedestrian_open` service used only for the popup action
- The extra popup control is capability-gated and appears only on supported TMT Chow gate entities
- Added the verified account `PS20040` / live `PS20040D` identity alias for family and UI capabilities, so the standalone Pedestrian opening entity and popup control are exposed on this controller variant
- PS20040D parameter access intentionally remains read-only for now; the PS20040 fallback schema is not promoted to a trusted write schema without independent D-variant write verification
- Treat invalid `DEV STATUS` battery values above 100% (including the observed `FF` → 127 sentinel) as unavailable instead of exposing impossible battery percentages

## v1.0.3

- Added model-gated pedestrian / partial opening control using the verified `PED OPEN` command
- Fixed a stale `DEV STATUS` stop-position update that could make a fully closed gate jump back to `open`
- Added ACK-loss tolerance for open/close/pedestrian movement commands when fresh telemetry proves the requested motion actually started
- Movement commands are never resent when an ACK is missing
- Added direct APK-derived support for the exact account `PS21050` / live `PS21050D` controller pair
- Finalized PS21050D as an exact 20-value `RP,1` / `WP,1` implementation; the four extra generated PS21050 definitions are treated only as normal/Hall overcurrent helper tables, not extra wire fields
- Added mode-aware opening/closing overcurrent selectors, including the vendor Hall-current wire offset
- PS21050D parameter writes now read the current frame first, change one field, validate all 20 values, send one `WP,1`, then verify by read-back; writes are never automatically retried
- Unsafe Motor Type transitions are rejected before writing if existing current values do not fit the target mode
- Unexpected PS21050D identity combinations remain raw/read-only instead of borrowing the PS21050 mapping
- Added the PS21050 pedestrian capability to the verified live PS21050D alias
- Corrected the distinction between Android `mUartVersion = 1` protocol selection and live Shadow `UART VER = 2` metadata
- Added `PS21050D_APK_MAPPING.md` documenting the exact vendor-app mapping and real-hardware frame
- Extended diagnostics with configured/live/parameter-model, codec and write-verification state
- Added regression tests plus a GitHub Actions test workflow for beta/main branches
- Hardened gate state tracking so late stale stopped `DEV STATUS` packets cannot flip a just-closed gate back to open or a just-opened gate back to closed

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