# TMT Chow v1.0.3

## Added

- Pedestrian / partial gate opening through the vendor `PED OPEN` command.
- A dedicated Home Assistant **Pedestrian opening** button for supported controller models.
- Direct APK-derived support for the verified TMT account `PS21050` / live `PS21050D` controller pair.
- Exact 20-value `RP,1` / `WP,1` PS21050D parameter handling derived from TMT Chow 3.1.4.
- Vendor parameter names and option tables for all 20 PS21050D wire fields, including mode-dependent normal/Hall overcurrent values.
- Extended diagnostics for configured/live controller identity, parameter profile, codec and write verification.
- GitHub Actions regression testing for integration changes.

## Fixed

- Fixed stale stopped `DEV STATUS` updates that could make a physically closed gate appear open in Home Assistant.
- Hardened endpoint state tracking so a late stale status packet cannot flip a just-closed gate back to open, or a just-opened gate back to closed.
- Added safe ACK-loss handling for `FULL OPEN`, `FULL CLOSE`, and `PED OPEN`: fresh matching telemetry can confirm execution, but movement commands are never automatically resent.
- Fixed controller-variant parameter bootstrap when live `DEV INFO` differs from the model returned by the TMT account API.
- Corrected PS21050D protocol interpretation: Android `mUartVersion = 1` selects `RP,1` / `WP,1`; live Shadow `UART VER = 2` is separate runtime metadata.

## PS21050D parameter safety

Before a PS21050D parameter write, the integration reads a fresh 20-value `RP,1` frame, changes exactly the requested field, validates the complete frame against the vendor option tables, sends one `WP,1`, then reads `RP,1` again and verifies the requested value. Parameter writes are never automatically retried.

Motor Type controls the two overcurrent option tables. Hall mode uses the vendor Hall-current table and wire offset. Unsafe Motor Type transitions are rejected before writing rather than silently changing current settings.

## Hardware validation

- `PS21053C`: pedestrian opening verified on real hardware with `ACK PED OPEN` and partial-position feedback.
- `PS21050D`: account model `PS21050`, live model `PS21050D`, 20-value parameter frame and Home Assistant state handling verified on real hardware.
- The final open/closed state correction was also verified on the live PS21050D installation before this stable release.

See `PS21050D_APK_MAPPING.md` for the complete vendor-app parameter mapping and protocol notes.
