# TMT Chow v1.0.4-beta.13

## Strict time-based pedestrian opening state lock

Real-device beta.12 testing showed that the cover could still flicker through `opening`, `closed`, and `closing` because a decreasing or stale dedicated `/position` update was allowed to override the pedestrian presentation state before the configured Pedestrian Mode time had elapsed.

Beta.13 makes the configured second-based Pedestrian Mode authoritative for the opening presentation window:

- once a timed PED cycle starts, Home Assistant remains `opening` for the full configured number of seconds;
- no ACK RS, Shadow, or `/position` direction/zero update can switch the presentation to `closing` or `closed` during that opening window;
- positive live positions are still recorded, and the highest observed partial position is retained for presentation so stale raw 0% cannot make the UI jump to 0%;
- only after the configured opening time expires can fresh post-window telemetry move the presentation to `closing`;
- a fresh dedicated live 0% after closing has been proven ends the cycle as `closed`;
- percentage-based and simple ON/OFF pedestrian modes remain telemetry-driven.

The logic remains schema-driven, so it applies to PS21053/PS21053C, PS25007 -> PS25007A, and other supported controller profiles whose active Pedestrian Mode option is expressed in seconds.

PS25007A command safety remains unchanged from beta.10.