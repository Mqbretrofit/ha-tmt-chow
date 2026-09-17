# TMT Chow v1.0.4-beta.27

## Restore verified PS25007A controls

This release restores the previously hardware-verified PS25007 account / PS25007A live-controller profile that was lost when later development branches were combined.

- Restores the exact `PS25007` account to `PS25007A` live identity mapping.
- Restores the verified 17-slot `RP,1` / `WP,1` parameter profile and named Home Assistant configuration entities.
- Accepts the live controller response and the 17-slot Shadow `dev_param` frame observed in diagnostics.
- Parameter writes always read the current complete frame first, send one full write with no automatic retry, and require an exact complete read-back match.
- Restores the requested PS25007A `PED OPEN` test path only for the exact live alias with an authenticated source tag while the gate is fully closed and stopped. It publishes exactly once and never retries automatically.
- Keeps unrelated controller profiles and the PS25142 OURANOS beta.26 work unchanged.

After updating, restart or reload the integration. The PS25007A configuration entities should populate from the verified 17-slot frame.
