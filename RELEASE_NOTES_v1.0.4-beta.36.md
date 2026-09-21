# TMT Chow v1.0.4-beta.36

## Pedestrian opening control fix

This beta fixes the Home Assistant control state after a successful pedestrian/partial opening.

Previously, some controllers could remain represented as still opening after the pedestrian cycle had effectively reached its partial position. Home Assistant would then disable Full Open and Close, leaving only Stop visible even though Stop could be ineffective in that state.

The integration now temporarily exposes the cover as an assumed state until authoritative stationary telemetry confirms the final pedestrian position. This keeps both **Close** and **Full Open** available for the user.

The temporary assumed state is cleared when:
- authoritative stopped telemetry arrives;
- the gate reaches a normal endpoint;
- Full Open, Full Close, or Stop takes over.

Normal Open / Close / Stop command handling, controller-specific safety gates, parameter handling, MQTT/native transports, and previously verified controller behavior are otherwise unchanged.

Regression tests cover the pedestrian post-open state and the return to normal full movement.
