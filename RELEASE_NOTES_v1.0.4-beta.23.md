# TMT Chow v1.0.4-beta.23

## PS25142 / AutoProduct read-only transport diagnostics

This beta extends the safe AutoProduct investigation introduced in beta.22 without enabling any new movement command or parameter write.

- Device discovery now preserves the vendor `uuid_type` field and Reconfigure refreshes it for existing entries.
- Diagnostics expose `uuid_type` so the Android `ConnectionFactory` transport choice can be compared with real hardware.
- The isolated `c=RS` diagnostic now records sanitized `wbt01Tx` traffic even when the response does not begin exactly with `ACK RS:`.
- `ACK RS` can be detected inside vendor wrappers for diagnostics while the normal live status parser remains unchanged.
- When the downloaded cloud Proposal declares `uartVer: V3.0`, diagnostics issue exactly one isolated `c=RP,1` parameter-read request and capture the sanitized response/traffic.
- The new probe never sends `WP,1`, `WRITE FUNCTION`, `FULL OPEN`, `FULL CLOSE`, `STOP`, `PED OPEN`, relay commands, learning commands, or any other write/movement operation.
- Regression tests cover raw/wrapped `ACK RS`, unrelated WBT traffic capture, identifier redaction, `uuid_type` discovery, and the single `RP,1` read-only request.

For issue #38 / PS25142, run **Reconfigure** once after updating so `uuid_type` is refreshed, then download a new diagnostics JSON. The combination of `uuid_type`, observed WBT traffic and the `RP,1` result should distinguish an RS-response-format issue from a different Android transport path.
