# TMT Chow v1.0.4-beta.9

## Isolated PS25007A pedestrian-opening experiment

This test build adds a deliberately separate Home Assistant service for one controlled real-hardware experiment on the exact configured `PS25007` -> live `PS25007A` alias.

The normal integration safety policy is unchanged:

- the ordinary pedestrian strategy for `PS25007` / `PS25007A` remains `none`;
- the normal pedestrian button/service still refuses direct `PED OPEN`;
- `RELAY4` remains disabled.

The experimental `tmt_chow.ps25007a_pedestrian_test` service is guarded by all of the following:

- configured account model must be exactly `PS25007`;
- live `DEV INFO` controller must be exactly `PS25007A`;
- the runtime source tag must be an account-derived non-anonymous `P...` tag, not `P9999999`;
- the gate must report fully closed (`0%`) and stopped before the test;
- the confirmation text must be exactly `PED OPEN <current source tag>`;
- a fresh read-only 17-slot `RP,1` parameter preflight must succeed immediately before the movement command;
- exactly one `PED OPEN` is handed to the existing no-resend movement-command path;
- no automatic retry and no follow-up open/close/stop command is issued.

A 35-second diagnostic capture window records inbound `wbt01Tx`, position and Shadow traffic for later inspection without exposing the experiment through the normal pedestrian entity.

This build exists only to reconcile the earlier unsafe `src=P9999999` manual test with the official app's successful pedestrian opening after beta.8 proved that the account-derived source tag works correctly for benign PS25007A parameter writes.
