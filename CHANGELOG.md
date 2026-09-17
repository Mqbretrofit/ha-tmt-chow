# Changelog

## Unreleased

- Keep the unknown-controller diagnostic matrix covering every APK read dialect in one download (`RS`, `READ STATUS`, `RP,1`, `READ FUNCTION`)
- Classify each dialect as ACK, NAK, or unresolved so a `NAK` stays in the report as rejected evidence instead of a working command
- Run the four WBT read probes one after another so each captured payload belongs to a single request
- Leave movement, learning and write commands catalogued but unsent
- Leave every verified controller runtime, movement, pedestrian and parameter-write path unchanged

## v1.0.4-beta.29
