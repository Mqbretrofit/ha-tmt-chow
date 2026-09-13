# TMT Chow v1.0.4-beta.4

This beta promotes the live-verified PS22027 20-value parameter profile from read-only diagnostics to guarded Home Assistant writes, while preserving the newer v1.0.4 runtime and pedestrian protections already present in beta.3.

## PS22027 parameter writes

- Enables the verified 20-slot `RP,1` / `WP,1` write path for PS22027.
- Every write starts with a fresh complete `RP,1` read.
- Only the selected raw slot is changed locally, then the complete mode-aware 20-value frame is validated.
- Exactly one `WP,1` command is sent; parameter writes are never automatically retried.
- A fresh `RP,1` read-back must match the entire requested 20-slot frame. Any collateral change in another slot is rejected.
- Hall Sensor opening/closing current selectors use the vendor P190 Hall-current option table and verified wire offset.
- Unsafe Function Mode transitions are blocked before any write when the existing current values would be invalid under the target mode.

## Diagnostics and regression protection

- Diagnostics distinguish the PS22027 write-verified profile from the former read-only profile and keep the existing pedestrian/FunctionSet evidence fields.
- Added regression tests for exact 20-value parsing, Hall mapping/encoding, single-write/read-back behavior, full-frame verification, collateral-change rejection, and unsafe mode-change blocking.

This is a beta because the write protocol is deliberately conservative and should receive additional real-device coverage across the remaining PS22027 settings before a stable promotion.
