# TMT Chow v1.0.4-beta.12

## Stable pedestrian/partial-opening state machine

Beta.11 tried to correct pedestrian movement state by rewriting the hub's raw `movement` / `is_operating` fields. Real-device testing showed that this still allowed Home Assistant to flicker between `opening`, `closed`, and other states as asynchronous RS, Shadow, and position updates arrived.

Beta.12 replaces that approach with a separate **presentation state machine** for the Home Assistant cover. Raw controller telemetry is still kept intact internally.

For controller profiles whose active Pedestrian Mode parameter is explicitly expressed in seconds:

- the presentation cycle starts **before** the PED command is published / waits for ACK;
- Home Assistant stays `opening` for the configured pedestrian opening duration even if transient RS or Shadow frames claim stopped/closed;
- at the configured time boundary the cover becomes partially `open`, not `closed`;
- after that boundary, a fresh closing operating-status or a decreasing dedicated `/position` value changes the display to `closing`;
- final live 0% (or a stopped 0% after closing has already been proven) ends the overlay and returns the cover to `closed`;
- full open / full close / stop commands cancel any active pedestrian presentation cycle;
- percentage-based partial opening and simple OFF/ON pedestrian modes are not treated as timers.

The logic is schema-driven, not hard-coded to one controller model, so it applies to PS21053/PS21053C, the verified PS25007 -> PS25007A alias, and other supported models whose vendor Pedestrian Mode is time-based.

PS25007A command safety remains exactly as in beta.10: exact alias gating, authenticated-user source tag, one `PED OPEN` publish, no movement-command retry, and no automatic follow-up movement command.