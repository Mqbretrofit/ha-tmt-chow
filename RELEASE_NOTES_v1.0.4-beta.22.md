# TMT Chow v1.0.4-beta.22

## AutoProduct / cloud Proposal discovery

This beta adds the first read-only implementation of the dynamic AutoProduct path identified in TMT Chow Android 3.2.0.

- During a new config-entry setup, the integration derives the seven-character PS/NP proposal id from the controller type.
- It requests the vendor endpoint `v4.0/devices/Proposal/{proposal}/latest/` with the same authenticated TMT session already used for device/AWS bootstrap.
- A missing Proposal is treated as a supported condition and does not break controllers that already use the verified static paths.
- The returned ResponseProposalInfo is stored with the config entry for offline runtime use; account credentials and Bearer tokens are not stored.
- Diagnostics expose a recursively redacted Proposal payload plus a compact summary of `proposalType`, version, UART version, gate type, ParameterSet/ParameterExt counts and FunctionSet evidence.
- The vendor spelling `fuctionSet` and the corrected `functionSet` are both supported.
- FunctionSet evidence such as `PED Open`, `Relay 1..4`, `Light` and `External` is reported, but **does not yet enable any new movement command or parameter write**.

The safety rule is intentional: the cloud Proposal is now observable first, so new controllers such as PS25142 can be mapped from vendor data and real hardware before dynamic commands are enabled.
