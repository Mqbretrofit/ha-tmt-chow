# TMT Chow v1.0.4-beta.7

## Diagnostics

- The v1.0.4-beta.6 probe confirmed the affected PS19001 returns AWS IoT Shadow GET `404` (`No shadow exists with name`), so the device does not have the classic unnamed Shadow that the current runtime normally uses for initial state synchronization.
- Added a second isolated read-only diagnostic probe for the legacy WBT status channel.
- The new probe subscribes only to `<uuid>/wbt01Tx`, publishes exactly one `c=RS` request to `<uuid>/wbt01Rx`, and waits for `ACK RS`.
- Diagnostics report whether the request was acknowledged, the raw `ACK RS` payload, whether it parsed successfully, and the decoded position / operating / direction / battery fields.

## Safety / scope

- `c=RS` is a status read only. The probe never sends `FULL OPEN`, `FULL CLOSE`, `PED OPEN`, `STOP`, parameter writes, or other control commands.
- The probe runs only while Home Assistant diagnostics are generated and uses its own temporary MQTT connection.
- Existing live hub availability rules, gate controls, parameter writes, discovery, AWS bootstrap and normal runtime subscriptions are unchanged in this build.

## Tests

- Added regression coverage proving the diagnostic probe subscribes only to `wbt01Tx` and publishes only one `c=RS` request.
- Added acknowledged/parsed, unrelated-response and no-response cases.
- Tests explicitly verify that no movement or parameter-write command is emitted by the probe.
