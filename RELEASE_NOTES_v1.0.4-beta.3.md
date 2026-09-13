# TMT Chow v1.0.4-beta.3

This beta consolidates the already-tested v1.0.4 work and adds narrowly scoped compatibility fixes while keeping unverified write paths disabled.

## Added

- Native-style **Pedestrian opening** control in the standard Home Assistant gate more-info popup for controllers with a verified safe pedestrian strategy.
- Explicit pedestrian command strategies (`ped_open`, `relay4`, `none`) with a hard safety block for direct `PED OPEN` on known-unsafe identities such as `PS25007A`.
- Verified `PS20040` / live `PS20040D` alias handling, including family/UI capability mapping and parameter writes through the existing read-before-write and read-back verification path.
- Exact `PS20005A` capability alias to APK-listed `PS20005` for issue #11. The concrete `PS20005A` identity is preserved; only PS20005 family/UI capabilities are reused, exposing pedestrian opening without borrowing a parameter schema or enabling parameter writes.
- Real-hardware-confirmed `PS22027` 20-value `RP,1` read-only parameter profile from issue #9 / issue9.3.
- PS22027 Hall Sensor current decoding through the vendor P190 Hall-current helper mapping.
- Expanded parameter diagnostics, including raw frame inspection, token counts and decoded PS22027 values.
- Staged AWS IoT connection diagnostics that identify DNS, TLS, TCP/8883, MQTT CONNACK and SUBACK failure stages.

## Fixed

- Replaced the misleading **Email address** login label with **Username / nickname** in all bundled translations.
- Invalid battery values above 100% (including the observed `FF` / 127 sentinel) are now treated as unavailable instead of being exposed as impossible percentages.
- MQTT connection warnings now include the connection stage, endpoint, exception type and non-empty error text.
- Initial AWS IoT setup waits long enough for a complete staged connection attempt before Home Assistant reports a setup timeout.

## Safety / validation

- `PS22027` parameter writes remain deliberately blocked. The experimental issue9.4 write path is **not** included in this release.
- `PS20005A` uses only an exact model alias; there is no generic suffix stripping and no guessed parameter codec.
- Existing protections from v1.0.3 remain in place, including stale stopped-status rejection, ACK-loss telemetry confirmation for movement commands, no automatic movement-command resend, and mandatory read-back verification for supported parameter writes.
- GitHub Actions regression suite: **46 tests passed** on the release branch before publication.

## Hardware validation status

Already validated behavior carried forward includes `PS21053C` pedestrian opening and the `PS21050` / live `PS21050D` 20-value parameter/state handling. The new `PS20005A` pedestrian alias is published for tester validation and issue #11 remains open until confirmed on matching hardware.
