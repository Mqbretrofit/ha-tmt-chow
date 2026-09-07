# PS25007A / AutoProduct pedestrian notes

This note records why `PS25007A` must not inherit the normal direct `PED OPEN` path without model-specific verification.

## TMT Chow 3.1.4 APK findings

The TMT Chow 3.1.4 APK does not expose a dedicated `PS25007A` product implementation in the static controller class catalog that is used by the integration's 217-model matrix.

The same APK contains the dynamic `AutoProduct` path and the following relevant identifiers/commands:

- `AutoProduct`
- `ResponseProposalInfo`
- `FunctionSet`
- `transferFunctionSet`
- `Relay 4`
- `RELAY4`
- `ACK RELAY4`
- `PED OPEN`
- proposal endpoint template: `v4.0/devices/Proposal/{proposal}/latest/`

This is important because an AutoProduct can derive UI/functions from a cloud proposal/FunctionSet instead of from a dedicated static controller class. A vendor-app pedestrian button therefore does **not** prove that the raw command for that controller is `PED OPEN`; the dynamic path also contains a separate Relay 4 mechanism.

## Real-hardware PS25007A evidence

GitHub issue #5 contains a real-hardware test for `P500BU,PS25007A,V02` performed before the integration exposed a pedestrian control for this model.

Observed after one manually patched direct `PED OPEN` command:

- the gate physically opened to roughly 50%;
- no `ACK PED OPEN` was received;
- the gate did not auto-close;
- the next normal `FULL CLOSE` executed with inverted physical direction and fully opened the gate;
- normal `FULL OPEN` / `FULL CLOSE` behavior returned only after recovery through the vendor app.

This is treated as a physical-safety signal, not merely an ACK compatibility issue.

## Integration policy

Starting in `v1.0.4-beta.1`:

- pedestrian control uses an explicit strategy: `ped_open`, `relay4`, or `none`;
- `PS25007A` is on a hard deny-list for direct `PED OPEN`;
- the deny-list wins even if a future capability import accidentally marks the model as pedestrian-capable;
- no controller is currently assigned to the `relay4` strategy;
- `RELAY4` must not be enabled for a concrete controller until its cloud FunctionSet and/or real-hardware behavior verifies that path;
- diagnostics expose the selected strategy and whether FunctionSet/Relay4 evidence is actually available.

The purpose is to avoid assuming that every vendor pedestrian UI button maps to the same raw movement command.
