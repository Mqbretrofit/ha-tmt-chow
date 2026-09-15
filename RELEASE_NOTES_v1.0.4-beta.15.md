# TMT Chow v1.0.4-beta.15

## PED closing state now follows Auto-closing time

Real-device testing confirmed that the timed pedestrian opening phase was correct in beta.14, but the displayed `closing` phase still started from raw telemetry instead of the controller's configured Auto-closing delay.

Beta.15 extends the pedestrian presentation state machine to use both controller timers:

- Pedestrian Mode seconds define how long Home Assistant shows `opening`;
- after that, Home Assistant shows `open` for the configured Auto-closing delay;
- when that Auto-closing timer expires, the display changes to `closing` immediately, without waiting for a possibly late or contradictory RS/Shadow frame;
- a fresh live 0% completes the cycle as `closed`;
- contradictory/stale closing telemetry is ignored while the configured open-hold timer is still active;
- if a controller exposes a dedicated `Auto-closing(Pedestrian Mode)` parameter, that value takes priority over normal Auto-closing;
- if the dedicated pedestrian auto-close setting is OFF, normal Auto-closing is not used as a fallback;
- if no dedicated pedestrian auto-close field exists, normal Auto-closing is used;
- Auto-closing OFF/unknown keeps the post-opening phase telemetry-driven.

For the verified 17-slot PS21053/PS21053C and PS25007 -> PS25007A profile, the same `automatic_closing` option shown by Home Assistant is used. With Pedestrian Mode = 6 seconds and Auto-closing = 30 seconds, the expected presentation is:

`opening` for 6 s -> `open` for 30 s -> `closing` -> fresh 0% -> `closed`.

PS25007A command safety rules remain unchanged.