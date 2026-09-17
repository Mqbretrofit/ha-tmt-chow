# TMT Chow v1.0.4-beta.29

## One diagnostic for unknown controllers

- Unknown or not-yet-verified controllers now receive a read-only discovery matrix when Home Assistant diagnostics are downloaded.
- The WBT/AWS path tests each APK 3.2.0 read dialect exactly once: `RS`, `READ STATUS`, `RP,1`, and `READ FUNCTION`.
- `uuid_type=1` OURANOS candidates also test `READ STATUS` and `RS` through the native route when the six-digit gate PIN has been saved in the integration options.
- The JSON records configured, live and Proposal identities; selected transport; AWS Shadow, WBT, OURANOS and Proposal/FunctionSet sources; sanitized responses and token shapes; working requests; blockers; and implementation readiness.
- The APK command catalog also lists movement, optional-control, learning and parameter-write commands, but diagnostics never transmit them.

## Restored verified controller support

- Restored the real-hardware-tested `PS22087` account / `PS22087B` live / `P710U` hardware mapping from the earlier beta branch.
- All 15 `F1..F9,A..F` fields are exposed; undocumented `B` and `D` remain read-only and are preserved verbatim.
- A change performs a fresh full read, exactly one full-frame write with no retry, and a mandatory full readback comparison.
- The earlier P710U entity unique IDs are retained so installations that used the test beta do not receive duplicate entities.

Beta.28's PS25007A pedestrian-button and translated-parameter fixes remain included. Existing verified PS21053C, PS21050C/D, PS22027, PS19001 and other controller routes are unchanged.
