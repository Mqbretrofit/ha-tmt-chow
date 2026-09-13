# Changelog

## v1.0.4-beta.4

- Enabled the real-hardware-verified PS22027 20-value `RP,1` / `WP,1` parameter write path without replacing the newer v1.0.4 runtime, pedestrian, MQTT, alias, or stale-position protections
- PS22027 writes now always read a fresh complete 20-value frame first, change only the requested slot, validate the full mode-aware frame, send exactly one `WP,1`, then read back the controller state
- Strengthened PS22027 write verification to require the entire returned 20-slot frame to equal the requested frame, so an unexpected collateral change to any other parameter is rejected
- Added PS22027 Home Assistant selectors with dynamic Hall Sensor current mapping from the vendor P190 helper table and the verified wire offset
- Diagnostics now report the PS22027 write-verified mapping profile while preserving the v1.0.4 pedestrian and FunctionSet evidence diagnostics
- Added regression coverage for Hall-current option encoding, successful single-write/read-back, full-frame collateral-change rejection, and unsafe Function Mode transition blocking

## v1.0.4-beta.3

- Added an exact `PS20005A` controller-identity alias for the APK-listed `PS20005` swing controller so its verified pedestrian capability is exposed without applying unsafe generic suffix stripping
- The `PS20005A` alias reuses only PS20005 family/UI capabilities; it does not borrow a parameter schema or enable parameter writes
- Added the real-hardware-verified PS22027 20-value `RP,1` read-only parameter profile from issue #9 / test build issue9.3
- PS22027 Hall Sensor mode now decodes the two overcurrent slots using the vendor P190 Hall-current mapping observed in the APK and verified against the captured 20-value live frame
- PS22027 parameter writes remain deliberately blocked until a real-hardware write/read-back test is confirmed; the experimental issue9.4 write path is not included
- Merged the PS22027 read-only diagnostics with the v1.0.4 pedestrian-strategy diagnostics, including raw parameter-frame inspection and a read-only diagnostics probe when normal bootstrap did not produce parameters
- Added regression tests for the exact PS20005A capability alias and for the PS22027 20-value parser, Hall mapping, live-frame decoding, `RP,1` refresh and write blocking

## v1.0.4-beta.2

- Replaced the misleading **Email address** login label with **Username / nickname** and updated the corresponding invalid-credentials message in all 23 bundled translations
- Added staged AWS IoT connection diagnostics that distinguish DNS resolution, TLS certificate/key setup, TCP/TLS reachability, MQTT CONNACK, and SUBACK failures
- MQTT connection warnings now always include the connection stage, endpoint, exception type and useful error text; empty `TimeoutError` messages are no longer logged as blank lines
- After a TLS connection failure the beta performs a non-MQTT TCP/8883 reachability probe to distinguish a blocked/unreachable port from a TLS/certificate/handshake problem
- Increased the initial AWS IoT setup wait to 60 seconds so one complete staged connection attempt can finish before Home Assistant reports a setup timeout
- Added regression tests for non-empty MQTT diagnostic exception formatting

## v1.0.4-beta.1

- Added a native-style fourth **Pedestrian opening** control directly inside the standard Home Assistant gate more-info popup for controllers with a safe verified pedestrian command strategy
- The popup button uses the controller's selected pedestrian strategy; it does not misuse Home Assistant tilt semantics
- The existing standalone Pedestrian opening button entity remains available
- Added a small frontend module loaded by the integration and a guarded `tmt_chow.pedestrian_open` service used only for the popup action
- Added explicit pedestrian command strategies: `ped_open`, `relay4`, and `none`
- Added a hard real-hardware safety block for direct `PED OPEN` on `PS25007A`; no pedestrian MQTT command is sent for this controller even if a future capability import accidentally marks it as supported
- `RELAY4` pedestrian infrastructure is present but has an empty controller allow-list; no controller can send `RELAY4` until its cloud FunctionSet / hardware behavior is explicitly verified
- Extended diagnostics with pedestrian strategy, strategy reason, direct-command safety block state, and explicit FunctionSet/Relay4 evidence fields so missing evidence is visible instead of guessed
- Added regression coverage proving `PS25007A` is blocked before MQTT transmission
- Added the verified account `PS20040` / live `PS20040D` identity alias for family and UI capabilities, so the standalone Pedestrian opening entity and popup control are exposed on this controller variant
- Enabled PS20040D parameter writes through the APK-derived PS20040 `RP,1` / `WP,1` schema for the exact configured `PS20040` + live `PS20040D` alias; the normal read-before-write and mandatory read-back verification remain active
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
