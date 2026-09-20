# Changelog

## Unreleased — issue #53 ARM64 / PS17062

- Add isolated ARM64/Bionic OURANOS support using the exact TMT Chow 3.1.5.33 ARM64 `libIOTCAPIs.so` / `libRDTAPIs.so` pair extracted from the public APK with strict size and SHA-256 verification
- Confirm on real PS17062/aarch64 hardware that `IOTC_Initialize2`, IOTC connect, RDT initialize/channel creation and `READ STATUS` all succeed
- Record the hardware response `ACK STATUS:PED CLOSED,2`; record that `RS` is rejected by this controller
- Promote the exact PS17062 + 20-character UID + `uuid_type=1` profile to automatic persistent native `READ STATUS` polling
- Add an explicit `tmt_chow.ps17062_movement_test` developer action for one-shot `FULL OPEN`, `FULL CLOSE` or `STOP` validation with explicit confirmation, fresh-state/end-position preconditions, no automatic retry, and one post-command `READ STATUS` verification
- Keep PS17062 movement/pedestrian controls disabled until separately hardware-verified
- Keep PS17062 parameter writes disabled and disable normal runtime parameter polling because the legacy `READ FUNCTION` route was not acknowledged
- Treat a successful native diagnostic read matrix as verified route evidence so diagnostics no longer report the obsolete “one read-only native status response is still required” blocker
- Preserve the existing PS19001, PS25142, x86-64/glibc, AWS/WBT and all other verified controller routes unchanged

## v1.0.4-beta.34

- Fix PS25142 issue #51 where a valid native `ACK RP,1` response could remain unavailable when the UART reply was wrapped as serialized JSON and ended with escaped CR/LF instead of a `;src=` suffix
- Unwrap the native OURANOS UART `DATA` field before PS25142 parameter decoding, including nested helper response envelopes
- Fix PS25142 diagnostics so the real RP,1 frame reports 18 tokens instead of counting JSON-envelope commas
- Expose the successfully decoded PS25142 18-slot values in diagnostics
- Add regression coverage for the exact issue #51 response: `ACK RP,1:1,8,0,3,0,1,5,0,0,0,0,2,3,0,0,0,1,1`
- Leave PS25142 movement/status handling and every previously verified controller route unchanged

## v1.0.4-beta.33

- Promote PS25142 from guarded testing to normal Home Assistant cover control after real hardware confirmed `FULL OPEN`, `FULL CLOSE`, `STOP` and live OURANOS/IOTC-RDT UART V3.0 `RS`
- Ignore the verified stale immediate post-STOP moving `RS` frame during a short settlement window and use read-only `RS` checks to settle the final state; STOP is never automatically resent
- Add the exact 18-slot PS25142 Proposal-B parameter profile (F1..FP + Fr), including Power saving mode
- Route PS25142 parameters over native UART V3.0 `RP,1` / `WP,1`
- Protect every PS25142 parameter change with a fresh full read, exactly one full-frame write with no retry, and mandatory full 18-slot readback equality
- Keep the native helper strictly allowlisted; arbitrary UART input remains unavailable
- Preserve PS19001 and all previously verified controller and parameter routes

## v1.0.4-beta.32

- Add an explicit PS25142 hardware movement-test action for `FULL OPEN`, `FULL CLOSE` and `STOP` over the already verified OURANOS/IOTC-RDT session
- Send exactly one movement command per action with no automatic retry, then perform one read-only `RS` refresh to capture the resulting live state
- Require fresh native status plus guarded end-position preconditions: open only from fully closed/stopped, close only from fully open/stopped, stop only while movement is reported
- Keep the normal PS25142 Home Assistant cover controls disabled; this beta is a deliberate Developer Tools test path only
- Persist the last sanitized movement-test result in diagnostics for one-file hardware feedback
- Leave PS19001 and every previously verified controller/parameter route unchanged

## v1.0.4-beta.31

- Promote the real-hardware-confirmed PS25142 route to automatic read-only native status: `uuid_type=1` → OURANOS/IOTC-RDT → UART V3.0 `RS` → `ACK RS`
- Decode the confirmed 9-byte `ACK RS` payload with the existing vendor status bit mapping and expose live cover availability/state
- Classify PS25142 as a sliding gate from its tested Proposal B metadata
- Keep PS25142 movement, pedestrian, relay, learning and parameter-write commands disabled until separately hardware-verified
- Preserve the existing PS19001 `READ STATUS` native session and all previously verified controller routes unchanged

## v1.0.4-beta.30

- Keep the unknown-controller diagnostic matrix covering every APK read dialect in one download (`RS`, `READ STATUS`, `RP,1`, `READ FUNCTION`)
- Classify each dialect as ACK, NAK, or unresolved so a `NAK` stays in the report as rejected evidence instead of a working command
- Run the four WBT read probes one after another so each captured payload belongs to a single request
- Leave movement, learning and write commands catalogued but unsent
- Leave every verified controller runtime, movement, pedestrian and parameter-write path unchanged

## v1.0.4-beta.29

- Restored the earlier real-hardware-verified `PS22087` account / `PS22087B` (`P710U`) 15-slot parameter profile, including its stable entity IDs and full-frame `RP,1` → one `WP,1` → `RP,1` verification path
- Added one read-only unknown-controller diagnostic matrix for the APK 3.2.0 WBT request dialects: `RS`, `READ STATUS`, `RP,1`, and `READ FUNCTION`
- Added both known OURANOS status-read dialects (`READ STATUS` and `RS`) to the same diagnostic for `uuid_type=1` devices when a local six-digit PIN is configured
- Added a route report covering configured/live/proposal identity, transport selection, cloud Proposal/FunctionSet, classic Shadow, WBT and OURANOS evidence, payload shapes, blockers, and implementation readiness
- Added an APK command catalog that records movement, optional-control, learning and write commands without ever transmitting those mutating commands during diagnostics
- Preserved beta.28 PS25007A UI/translation fixes and every existing controller-specific runtime and parameter route
