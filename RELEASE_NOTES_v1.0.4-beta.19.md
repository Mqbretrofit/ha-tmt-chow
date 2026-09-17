# TMT Chow v1.0.4-beta.19

This beta enables model parameters for the exact `PS21050` account / `PS21050C` live-controller pair confirmed in issue #11.

## Write safety

- Reads the fresh complete 20-slot `RP,1` frame before every change.
- Changes only the selected field in memory.
- Validates the complete frame with the existing APK-derived PS21050 codec.
- Sends exactly one complete `WP,1` frame with no automatic retry.
- Reads `RP,1` again and accepts the change only when all 20 fields match exactly.

The existing `PS21050D` behavior and all unrelated controller paths remain unchanged.
