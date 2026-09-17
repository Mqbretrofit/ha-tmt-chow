# TMT Chow v1.0.4-beta.18

This beta adds explicit support for the `PS21050C` live controller reported in issue #11.

## Changes

- Recognizes the exact `PS21050` account / `PS21050C` live identity pair without generic suffix stripping.
- Restores the `PS21050` swing-family and pedestrian capability metadata for that pair.
- Uses the proven 20-slot `PS21050D` `RP,1` decoder for the matching real-hardware `PS21050C` frame.
- Keeps the concrete `PS21050C` identity visible in diagnostics.
- Keeps all `PS21050C` parameter writes disabled pending separate real-hardware verification.

The existing `PS21050D` read/write path and all unrelated controller behavior remain unchanged.
