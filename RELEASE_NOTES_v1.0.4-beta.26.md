# TMT Chow v1.0.4-beta.26

## Add a Proposal-aware read-only PS25142 OURANOS status probe

This release continues the safe PS25142 investigation from beta.25. The previous probe confirmed that the native OURANOS / ThroughTek IOTC-RDT transport works, but the controller rejected the legacy `READ STATUS` request with `NAK READ STATUS`.

- Vendor-identified OURANOS entries with `uuid_type: "1"` and a stored AutoProduct Proposal reporting `uartVer: V3.0` now use the read-only UART status request `RS` in the isolated `tmt_chow.ouranos_probe` action.
- Verified PS19001 controllers keep their existing `READ STATUS` request and automatic native polling behavior.
- PS25142 remains probe-only. Automatic native polling, movement commands, relay/learning commands, parameter reads, and parameter writes are still disabled.
- The sanitized service response now reports which allowlisted status command was selected.
- Native framing and regression tests cover both `READ STATUS` and `RS`, Proposal-based selection, legacy PS19001 compatibility, and the command-safety boundary.

For PS25142 testing, update to beta.26 and run `tmt_chow.ouranos_probe` again with the same six-digit gate PIN. Keep the gate stationary and return only the service response. Never post the PIN.
