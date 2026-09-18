# TMT Chow v1.0.4-beta.31

## PS25142 live status support

Issue #38 / beta.30 provided the missing real-hardware runtime evidence for PS25142:

- vendor transport: `uuid_type=1` / OURANOS / ThroughTek IOTC-RDT
- cloud profile: Proposal B, UART V3.0, sliding gate
- accepted status request: `RS`
- real response: `ACK RS:00,00,A2,02,40,00,FF,FF,FF`

Beta.31 turns that verified read-only route into normal Home Assistant status polling when the six-digit gate PIN is saved in the integration options. The returned `ACK RS` frame is decoded by the same vendor status mapping already used for WBT `RS` frames, and a recent valid native response now makes the cover available.

## Safety boundary

PS25142 is status-only in this release. The cover does not expose open/close/stop controls for this profile, and the integration does not enable pedestrian, relay, learning or parameter-write commands from Proposal metadata alone. Those mutating paths remain disabled until they have separate real-hardware validation.

PS19001 keeps its existing `READ STATUS` native polling and command-capable persistent session unchanged. All established WBT/MQTT controllers and verified parameter profiles are unchanged.
