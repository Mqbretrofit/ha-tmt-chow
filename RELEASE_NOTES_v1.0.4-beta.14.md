# TMT Chow v1.0.4-beta.14

## Fix PED state wrapper bypass from the cover more-info control

Real-device history from beta.13 showed the timed pedestrian display state was not active on the tested path: with Pedestrian Mode configured to 6 seconds, the cover stayed `opening` for much longer, then fell back to raw `closed`/`closing`/`opening` transitions.

Root cause: the custom cover more-info PED control calls the integration service `tmt_chow.pedestrian_open` directly, while beta.12/beta.13 only armed the pedestrian presentation state inside the separate ButtonEntity. The service therefore bypassed the state machine entirely.

Beta.14 fixes the command entry-point mismatch:

- both the normal Pedestrian ButtonEntity and the custom cover more-info PED control now call one shared `async_pedestrian_open_with_display()` wrapper;
- the timed presentation state is armed before the controller command from either entry point;
- command failure/cancellation clears the presentation overlay cleanly;
- PS21053/PS21053C and PS25007 -> PS25007A read the 17-slot Pedestrian Mode duration from the same `parameters.PARAMETERS` option source used by their Home Assistant select entities;
- other second-based pedestrian profiles remain schema-driven;
- the beta.13 strict opening lock remains: raw RS, Shadow, and `/position` changes cannot end the configured opening window early.

PS25007A command safety is unchanged.