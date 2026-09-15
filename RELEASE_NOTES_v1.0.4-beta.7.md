# TMT Chow v1.0.4-beta.7

This beta adds model-specific parameter support for the observed TMT account/live identity pair **PS25007 -> PS25007A** (`P500BU,PS25007A,V02`).

## PS25007 / PS25007A parameters

- Uses the TMT Chow 3.1.4 AutoProduct Proposal for `PS25007`, which declares the complete 17-slot F1..FP parameter order.
- Real PS25007A hardware confirmed that the Proposal order matches the live 17-value `DEV PARAM` frame; F7 / Overcurrent was independently verified on wire slot 7.
- The 12 Overcurrent values were verified as raw 0..11 = 2 A..13 A.
- Exposes all 17 parameters as the normal localized Home Assistant configuration selectors instead of temporary raw diagnostic sensors.
- The exact account/live alias is required; no generic model-suffix fallback is added.

## Write safety

- A safe `RP,1` full-frame read is performed before every parameter write.
- Only the requested slot is changed in memory.
- Exactly one complete `WP,1` frame is transmitted; parameter writes are never automatically retried.
- The integration then performs another `RP,1` read and requires **all 17 returned slots** to exactly match the requested frame.
- Any collateral parameter change or mismatched read-back is rejected.
- Parameter writing is enabled only after live `DEV INFO` confirms `PS25007A`; the initial account-only `PS25007` phase is read-only.

## Pedestrian-opening safety is unchanged

Parameter support does **not** authorize a pedestrian movement command. Real-hardware evidence showed that direct `PED OPEN` on PS25007A can leave the controller in an unsafe internal state and invert the next movement command.

- Direct `PED OPEN` remains hard-blocked for both `PS25007` and `PS25007A` identities.
- `RELAY4` remains disabled.
- No pedestrian command path is enabled by this beta.

## Testing

The first live write should use a benign setting and confirm that the Home Assistant value and the vendor app agree after read-back before broader parameter testing.
