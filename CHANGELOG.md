# Changelog

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
