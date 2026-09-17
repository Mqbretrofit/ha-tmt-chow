# TMT Chow v1.0.4-beta.24

## PS25142 / uuid_type 1 OURANOS probe

This beta follows the beta.23 hardware diagnostics for issue #38 and keeps the new controller path strictly read-only.

- The vendor `uuid_type` value is now used as transport evidence for the isolated `tmt_chow.ouranos_probe` service. `uuid_type: "1"` is accepted as an OURANOS / ThroughTek IOTC-RDT candidate, matching the TMT Chow 3.2.0 ConnectionFactory behavior identified from the APK.
- The legacy PS19001 fallback remains available for older entries created before `uuid_type` persistence was added.
- Automatic native polling and command-capable persistent sessions remain restricted to the already verified PS19001 path. PS25142 and other newly identified OURANOS devices are probe-only in this beta.
- The OURANOS probe still sends exactly one APK-compatible read-only `READ STATUS` request. It does not send movement, relay, learning, parameter-read, or parameter-write commands.
- AutoProduct FunctionSet parsing now recognizes the vendor `dCmd` field, so Proposal B entries such as `PED Open` are reported correctly.
- Localized gate type `橫拉門` (and simplified `横拉门`) is recognized as a sliding gate.
- Regression tests cover `uuid_type: 1` probe-candidate detection, WBT rejection for unknown controllers, the legacy PS19001 fallback, `dCmd`, and the localized sliding-gate name.

For PS25142 testing, call `tmt_chow.ouranos_probe` with the configured gate UUID and its six-digit TMT Chow PIN, then return the service response. No gate movement is performed by this probe.