# TMT Chow v1.0.3-beta.1

Beta release for live testing before the next stable version.

## Added

- Pedestrian / partial gate opening through the vendor `PED OPEN` MQTT command.
- A dedicated Home Assistant **Pedestrian opening** button.
- The button is created only for controller models whose pedestrian control is exposed by the TMT Chow / gatePRO app capability matrix.
- `PS21053C` has been verified on real hardware with `ACK PED OPEN` and a partial position update.

## Fixed

- Prevent a stale `DEV STATUS` position from contradicting the direction of the movement that just completed. This addresses issue #5 where a physically closed gate could jump back to `open` in Home Assistant.
- If an `ACK FULL OPEN`, `ACK FULL CLOSE`, or `ACK PED OPEN` is lost, Home Assistant now accepts the command as successful only when fresh post-command telemetry proves that the requested movement actually started.
- A missing ACK never causes the movement command to be resent.

## Notes

This is a beta build. The pedestrian command is live-tested on PS21053C. Availability on other controller models follows the vendor APK/XAPK capability mapping until separately validated on matching hardware.
