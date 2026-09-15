# PS25007A / AutoProduct pedestrian notes

This note records the current evidence for the `PS25007` account identity whose live controller reports `PS25007A` (`P500BU,PS25007A,V02`). Parameter support and pedestrian-command safety remain separate decisions.

## TMT Chow 3.1.4 APK and Proposal findings

The TMT Chow 3.1.4 APK uses its dynamic `AutoProduct` path for this product. The relevant logic is:

- normal pedestrian path: `PED OPEN`
- alternate path: `RELAY4`
- `Relay 4` in the cloud `FunctionSet` is what switches AutoProduct to the alternate path

The cloud Proposal requested with the account product identity `PS25007` explicitly declares:

- `PED Open`
- notifications `PedOpening` and `PedOpened`

The same PS25007 Proposal does **not** declare a `Relay 4` FunctionSet command. With that Proposal, the APK therefore predicts the direct `PED OPEN` path rather than `RELAY4`.

The UART-v1 command builder also contains two source identities:

- identified-user form: `;src=P%07X(user_id)`
- privacy/GDPR anonymous form: `;src=P9999999`

The exact privacy branch taken by the official app on this account has not yet been captured directly.

## Real-hardware evidence

### Official app

The official TMT Chow app was tested on the real `P500BU,PS25007A,V02` controller and its pedestrian-opening action works correctly.

A later passive MQTT capture on the correct PS25007 device observed the resulting controller traffic, including movement/status updates and a final `40%` position. The AWS IoT policy accepted subscriptions to `wbt01Tx`, `/position` and Shadow documents, but disconnected the passive client when it attempted to subscribe to outbound `wbt01Rx`. Because of that policy restriction, the exact command payload/source tag sent by the official app was not visible in the passive capture.

### Earlier manual direct-command test

An older unofficial test sent one manually constructed direct command using `c=PED OPEN;src=P9999999` on the same controller family. That test produced a serious unsafe state:

- the gate physically opened to roughly 50%;
- no expected `ACK PED OPEN` was received;
- the gate did not auto-close;
- the next normal `FULL CLOSE` executed with inverted physical direction and fully opened the gate;
- normal `FULL OPEN` / `FULL CLOSE` behavior returned only after recovery through the vendor app.

This remains a physical-safety signal even though the official app can perform pedestrian opening correctly.

## Current hypothesis and integration policy

The strongest unresolved context difference is now the command source identity. The integration historically stores `P9999999`, while the APK has an identified-user `P%07X(user_id)` path. Starting with `v1.0.4-beta.8`, the exact configured `PS25007` beta profile can refresh its source tag from the authenticated user profile through Home Assistant Reconfigure.

This is an experiment to align command identity with the APK path, not proof that `P9999999` caused the earlier unsafe behavior.

Until that difference is verified safely:

- `PS25007` and `PS25007A` remain hard-blocked for direct `PED OPEN`;
- `RELAY4` remains disabled because the PS25007 Proposal does not map pedestrian opening to Relay 4;
- no pedestrian movement command should be manually injected merely to test the hypothesis;
- benign command/parameter behavior with the refreshed source tag should be verified before considering any change to the pedestrian safety block.
