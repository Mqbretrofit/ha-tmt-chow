# TMT Chow v1.0.4-beta.10

## Verified PS25007A pedestrian opening

This beta enables the normal pedestrian/partial-opening control only for the exact configured `PS25007` -> live `PS25007A` alias after the account-derived authenticated-user source tag has been established.

Real-hardware verification on `P500BU,PS25007A,V02` showed that one command using the authenticated-user source tag (`PED OPEN;src=P00317D9` on the tested account) performs the same vendor pedestrian cycle seen in the official TMT Chow app: the gate opens to the pedestrian position (observed at 40%) and then automatically closes back to 0%.

The controller did not emit `ACK PED OPEN`. For this verified alias the integration therefore:

- sends `PED OPEN` exactly once;
- never automatically retries the movement command;
- does not require `ACK PED OPEN`;
- lets `ACK RS`, `/position`, and Shadow telemetry report the resulting movement/state;
- requires the gate to be fully closed and stopped before the pedestrian command is sent;
- requires a valid account-derived source tag and refuses the anonymous `P9999999` source.

The generic PS25007/PS25007A direct-command deny-list remains in place for all other contexts. The exception is implemented only in the exact PS25007 -> PS25007A runtime alias with the identified source tag, so startup timing, unrelated controller identities, or anonymous source tags do not gain pedestrian control.

Parameter support from beta.8 is unchanged: 17-slot RP,1/WP,1 writes still use read-before-write, exactly one write, and complete-frame read-back verification.
