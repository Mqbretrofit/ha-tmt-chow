# TMT Chow v1.0.4-beta.37

## PS24118 / PS24118C standby-state fix

- Added explicit support for the observed `P190U,PS24118C,V02` live identity.
- Reuses only the verified P190U swing-family and pedestrian UI capability metadata.
- Keeps parameter writes disabled for PS24118/PS24118C; no P190U parameter schema is borrowed.
- Uses read-only `RS` status refreshes after Full Open, Full Close and Pedestrian Open, plus periodic live polling while connected.
- Prevents stale classic-Shadow `DEV STATUS` from overwriting fresh live RS state on this exact profile.
- Movement commands are still transmitted exactly once and are never automatically retried.

This beta is intended for testing GitHub issue #57, especially the Open/Closed state after at least 3 minutes of standby in both directions.
