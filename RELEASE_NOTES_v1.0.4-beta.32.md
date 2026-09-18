# TMT Chow v1.0.4-beta.32

## Guarded PS25142 movement hardware test

Beta.31 confirmed normal live PS25142 status on real hardware. Beta.32 adds the next deliberately narrow validation step without enabling normal cover control.

A new Home Assistant action, `tmt_chow.ps25142_movement_test`, is available only for the exact verified PS25142 profile:

- `uuid_type=1`
- OURANOS / ThroughTek IOTC-RDT
- Proposal B / sliding gate
- UART V3.0
- verified `RS` / `ACK RS` status route

The action supports only `open`, `close`, and `stop`. Each call can send exactly one allowlisted movement command (`FULL OPEN`, `FULL CLOSE`, or `STOP`) and never retries it automatically. One read-only `RS` refresh follows the command so the service response and diagnostics can show the resulting live state.

## Safety guards

- `open` is accepted only when fresh native status says the gate is fully closed and stopped.
- `close` is accepted only when fresh native status says the gate is fully open and stopped.
- `stop` is accepted only while fresh native status reports movement.
- `confirm=true` is required on every call.
- Normal PS25142 cover movement controls remain disabled.
- Pedestrian, relay, learning, reset and parameter-write commands remain disabled for PS25142.

PS19001 and all other existing verified controller paths remain unchanged.
