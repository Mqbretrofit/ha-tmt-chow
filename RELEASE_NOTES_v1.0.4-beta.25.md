# TMT Chow v1.0.4-beta.25

## Finalize PS25142 / uuid_type 1 read-only OURANOS probe

This release supersedes beta.24 and contains the same PS25142 read-only transport step plus the final regression/compatibility fixes verified by the full test suite.

- Controllers returned by the TMT cloud with `uuid_type: "1"` can use the isolated `tmt_chow.ouranos_probe` service, matching the OURANOS / ThroughTek IOTC-RDT transport identified from TMT Chow 3.2.0 and the existing standalone probe tooling.
- Existing pre-`uuid_type` PS19001 installations keep their verified legacy OURANOS fallback.
- Automatic native polling and the persistent command-capable OURANOS session remain restricted to the already verified PS19001 path. PS25142 remains probe-only in this release.
- The isolated probe sends exactly one APK-compatible read-only `READ STATUS` request. It does not send movement, relay, learning, parameter-read, or parameter-write commands.
- AutoProduct FunctionSet parsing recognizes the vendor `dCmd` field, including `Open`, `Stop`, `Close` and `PED Open`.
- Localized gate type `橫拉門` (and simplified `横拉门`) is recognized as a sliding gate.
- Regression coverage verifies `uuid_type: 1`, rejects WBT transport metadata for unknown controllers, preserves the PS19001 fallback, and covers Proposal B metadata parsing.

For PS25142 testing, update to beta.25 and call `tmt_chow.ouranos_probe` with the gate UUID (optional if there is exactly one OURANOS candidate) and the six-digit TMT Chow gate PIN. Return the service response only; never post the PIN.