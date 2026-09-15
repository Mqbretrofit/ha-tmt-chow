# TMT Chow v1.0.4-beta.11

## Timed pedestrian movement state

This beta fixes the Home Assistant opening/closing state shown during pedestrian/partial opening for controllers whose vendor **Pedestrian Mode** parameter is expressed as a number of seconds.

The fix is deliberately model-generic instead of being hard-coded to PS25007A. The runtime inspects the active controller parameter schema and current confirmed parameter values:

- second-based Pedestrian Mode options (for example 3/6/9/12/15/18 seconds) define the temporary `opening` state window;
- interim controller direction/status frames cannot incorrectly flip that pedestrian opening to `closing` before the configured opening time has elapsed;
- a decreasing live `/position` value is stronger evidence and immediately ends the timed opening window so automatic closing is shown as `closing`;
- after the configured opening time expires, the forced `opening` state is released and normal live telemetry takes over;
- percentage-based pedestrian opening and simple OFF/ON pedestrian modes are not treated as timers.

This covers the verified PS21053/PS21053C 17-slot profile, the PS25007 -> PS25007A alias, and other controller schemas where the vendor APK defines Pedestrian Mode in seconds.

The PS25007A command safety rules from beta.10 are unchanged: identified source tag required, one `PED OPEN` publish only, no movement-command retry, and no follow-up movement command.