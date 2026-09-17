# Changelog

## v1.0.4-beta.21

- Added a targeted PS19001 entity-registry cleanup for the four unavailable parameter entities left by the obsolete 23-slot profile
- Removes only `parameter_20` through `parameter_23` for the same config entry and only when the live-verified 19-slot PS19001 profile is active
- Preserved all 19 working PS19001 parameters, their entity IDs, native control/status behavior, and every other controller path

## v1.0.4-beta.20

- Corrected PS19001 parameters to the live-hardware-confirmed 19-slot UART0 frame labelled `1` through `J`
- Removed the four inherited P190 current lookup helpers from the wire/entity list; they now only select the normal or Hall Sensor current mapping
- Added strict parsing of the real JSON-wrapped `ACK READ FUNCTION` response and exact full-frame `WRITE FUNCTION,1...J` encoding
- Kept parameter mutation guarded by a fresh read, exactly one write with no retry, and an exact complete 19-slot readback
- Rebuilt and integrity-pinned the native helper so the obsolete zero-based 23-slot frame is rejected before transmission
- Preserved all proven PS19001 movement/status behavior and every non-PS19001 controller path

## v1.0.4-beta.19

- Enabled the APK-derived 20-slot parameter controls for the exact `PS21050` account / `PS21050C` live-controller pair
- Added a guarded `RP,1` → single `WP,1` → `RP,1` transaction with no automatic write retry
- Requires the complete 20-slot readback to match on `PS21050C`, rejecting any unexpected collateral field change
- Preserved the existing `PS21050D` write behavior and every unrelated controller path

## v1.0.4-beta.18

- Added an exact `PS21050` account / `PS21050C` live-controller alias based on issue #11 real-hardware diagnostics
- Reused the proven 20-slot `PS21050D` RP,1 read codec for `PS21050C`, while preserving the concrete live model identity
- Restored the APK-derived swing family and pedestrian capability so the pedestrian control is exposed with the existing guarded `PED OPEN` strategy
- Kept all `PS21050C` parameter writes disabled until separately verified on real hardware
- Added regression coverage for the reported 20-slot frame, enabled pedestrian field, read-only parameter safety, and unchanged `PS21050D` behavior

## v1.0.4-beta.17

- Added native PS19001 full-open, full-close, stop and pedestrian-open control over the already proven persistent IOTC/RDT session
- Added native `READ FUNCTION` and full-frame `WRITE FUNCTION` support for all 23 APK-derived PS19001 parameters
- Kept parameter writes transactional: fresh full read, exactly one write with no automatic retry, then mandatory readback verification
- Restricted the native helper to fixed movement/read operations and a validated UART0 parameter-frame grammar; arbitrary wire commands remain rejected
- Left every non-PS19001 AWS/MQTT control and parameter path unchanged

## v1.0.4-beta.16

- Replaced repeated PS19001 status reconnects with one persistent, isolated IOTC/RDT session for both automatic and manual status refreshes
- Added a separate integrity-pinned native session helper that accepts only `STATUS` and `QUIT` and can transmit only the fixed `READ STATUS` request
- Automatically discards a timed-out, malformed or dead native session so a later poll can establish a clean replacement
- Closes the persistent helper during integration unload and reports its connection state in privacy-safe diagnostics
- Kept the original one-shot diagnostic action, AWS/MQTT gate controls and all controller parameter behavior unchanged

## v1.0.4-beta.15

- Reduced PS19001 native connection pressure by changing successful polling from 5 to 15 seconds and failed retries from 30 to 60 seconds
- Extended native cover availability from 30 seconds to 15 minutes so a short-lived RDT failure does not immediately discard a valid last-known state
- Added a **Refresh native gate status** button that remains available for manual recovery even while the cover is unavailable
- Serialized automatic and manual native refreshes so multiple IOTC/RDT helper sessions cannot run concurrently for one gate
- Added privacy-safe diagnostics for the last attempt, last success, last result, status age, consecutive failures and refresh activity
- Preserved the fixed read-only `READ STATUS` safety boundary and all existing AWS/MQTT control paths

## v1.0.4-beta.14

- Added opt-in automatic PS19001 native cover status for the confirmed 20-character UID case, using the real-hardware-verified `ACK STATUS:PED CLOSED,0` response
- Added a password-style integration option for the six-digit gate PIN; it is stored locally and redacted from diagnostics
- Mapped native position and opening/closing state into the existing Home Assistant cover while leaving all movement commands on the unchanged AWS/MQTT path
- Removed the obsolete two-second passive read before each fixed status request, added failure backoff, process-cancellation cleanup and native availability expiry handling
- Kept the native helper restricted to one fixed `READ STATUS` request with no arbitrary, movement, function or parameter command input

## v1.0.4-beta.13

- Added the fixed, APK-compatible, PIN-XOR `READ STATUS` request and sanitized `ACK STATUS` response to the isolated PS19001 helper
- Preserved the executable mode of the bundled helper in the published release archive

## v1.0.4-beta.11

- Replaced the legacy Linux x86-64 IOTC 1.13.7.0 / RDT 1.7.4.0 probe libraries with IOTC/RDT 3.1.5.38 from the same 3.1.5 API generation as the TMT Chow Android application's IOTC 3.1.5.33 library
- Pin both native files to an immutable source commit and verify each file with its own SHA-256 before installation
- Download only the two required native files instead of extracting an entire third-party SDK archive
- Kept the private glibc runtime, helper-process isolation, confirmed-PS19001 restriction and read-only/no-command safety guarantees unchanged

## v1.0.4-beta.10

- Raised the private glibc download safety ceiling from 32 MiB to 64 MiB so the verified 52,484,557-byte runtime archive can be accepted
- Kept the pinned SHA-512 integrity verification unchanged; an oversized or hash-mismatched archive is still rejected before extraction
- Added regression coverage for the exact archive size reported by the first beta.9 PS19001 test

## v1.0.4-beta.9

- Added an experimental, read-only PS19001 OURANOS transport probe directly to the TMT Chow integration; no separate Home Assistant add-on is required
- Matched the TMT Chow 3.1.4 application flow: `IOTC_Initialize2(0)` → parallel UID connection → `RDT_Initialize()` → `RDT_Create(session, 5000, 0)` → passive `RDT_Read()`
- Replaced the incompatible combined, license-key-dependent 4.2.x TUTK library with separately loaded legacy Linux x86-64 IOTC 1.13.7.0 and RDT 1.7.4.0 libraries, pinned by source commit and SHA-256
- Run the native libraries in a separate helper process through a private integrity-checked glibc runtime, keeping native failures isolated from Home Assistant Core
- Restricted the probe to confirmed 20-character PS19001 candidates and x86-64 Home Assistant systems; other controllers and architectures are not guessed
- Kept the probe transport-only: it binds no `RDT_Write` symbol and sends no open, close, stop, status-read, function-read, or parameter-write payload
- Added library extraction, helper-integrity, UUID redaction, candidate-selection and no-write regression coverage

## v1.0.4-beta.5

- Fixed account discovery so otherwise valid devices are no longer discarded when the device-list API returns `iot_endpoint: null`
- Confirmed the observed PS19001 / `product_type: 108` account shape can be discovered from UUID and model metadata even when the endpoint is omitted from the device list
- Preserved the existing AWS certificate/policy bootstrap as the next endpoint source; MQTT connection, subscription, publishing and gate-command behavior are unchanged
- Added regression coverage for the null-endpoint PS19001 discovery case while verifying existing endpoint-bearing devices still behave unchanged

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
