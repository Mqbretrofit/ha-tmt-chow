# TMT Chow v1.0.4-beta.33

## PS25142 final runtime profile

PS25142 is promoted from the guarded test path to normal Home Assistant cover control after real-hardware confirmation of:

- OURANOS / ThroughTek IOTC-RDT transport
- UART V3.0 `RS` / `ACK RS` live status and position
- `FULL OPEN` / `ACK FULL OPEN` with physical opening
- `FULL CLOSE` / `ACK FULL CLOSE` with physical closing
- `STOP` / `ACK STOP` with physical stop

The controller can return one stale moving `RS` sample immediately after `ACK STOP`. Beta.33 keeps the acknowledged stopped state during a short settlement window and uses read-only `RS` checks to obtain the stable state. The STOP command itself is never retried.

## PS25142 parameters

The tested cloud Proposal B contains 18 parameter slots (F1..FP plus Fr). Beta.33 exposes all 18 as Home Assistant configuration selects, including the additional Power saving mode.

The parameter route uses the controller's UART V3.0 AutoProduct transport:

- read: `RP,1`
- read acknowledgement: `ACK RP` / `ACK RP,1`
- write: `WP,1:<18 values>`
- write acknowledgement: `ACK WP`

Every parameter mutation is guarded by a fresh complete read, exactly one complete write frame with no automatic retry, and a complete 18-slot readback that must exactly match the requested frame. A mismatch is rejected.

The 18-slot layout and allowed values come from the controller's own tested Proposal B metadata. The transport and full-frame transaction are vendor AutoProduct protocol-derived; parameter mutation on this exact PS25142 hardware has not yet been independently exercised, so the strict read-before-write/readback guard remains in place.

## Compatibility

Existing PS19001 and all previously verified controller-specific routes remain unchanged.
