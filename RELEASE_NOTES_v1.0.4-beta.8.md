# TMT Chow v1.0.4-beta.8

## Experimental PS25007 command source identity

This beta aligns the configured `PS25007` profile with the identified-user UART-v1 source format found in the TMT Chow 3.1.4 Android app.

- New `PS25007` setups read the authenticated `/v4.0/user/` profile id and format the command source as `P%07X`.
- Existing entries can use Home Assistant **Reconfigure** to refresh only the command source tag. The existing AWS IoT certificate, private key and device selection are preserved.
- The setup/reconfigure password is used only for authentication and is not stored.
- Other controller models keep their existing source-tag behavior in this beta, limiting the change to the hardware profile under investigation.

## Safety status

This does **not** enable pedestrian opening on PS25007/PS25007A.

- Direct `PED OPEN` remains hard-blocked for both `PS25007` and `PS25007A`.
- `RELAY4` remains disabled.
- No movement command is enabled or newly transmitted by this source-tag change.

The PS25007 Proposal and APK both point to direct `PED OPEN`, and the official app has now been observed performing a correct pedestrian opening on the real `P500BU,PS25007A,V02` controller. A passive capture confirmed the resulting controller state/position traffic but the AWS policy rejected subscription to the outbound `wbt01Rx` topic, so the exact app-side source tag could not be captured directly.

The older unsafe manual test used `src=P9999999`. The identified-user source tag is therefore being tested as an important context difference, **not** treated as proven root cause. The pedestrian safety block stays in place until that difference is verified under controlled conditions.
