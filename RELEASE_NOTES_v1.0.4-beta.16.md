# TMT Chow v1.0.4-beta.16

## Fix pedestrian state when Auto-closing is OFF

Real-hardware testing on a second PS25007A confirmed that beta.15's physical `PED OPEN` command is correct with an authenticated-user source tag, but exposed one remaining Home Assistant state issue when `Auto-closing = OFF`.

After the timed pedestrian opening phase, the gate could remain physically parked at its partial-open position while a single stale `/position = 0%` update caused the presentation state to collapse from `open` to `closing` and immediately to `closed`. Home Assistant then disabled the Close control even though the gate was still physically open.

Beta.16 hardens the telemetry-driven Auto-closing-OFF path:

- one isolated decreasing or 0% `/position` update is no longer enough to leave the pedestrian `open` state;
- two consecutive decreasing dedicated `/position` updates are required to confirm real reverse travel when no auto-close timer is configured;
- a rebound such as `40% -> 0% -> 40%` resets the false closing candidate and keeps the displayed state `open`;
- repeated fresh `is_operating + closing` status frames can also confirm closing on controllers without useful live position updates;
- while the PED overlay remains `open`, the highest verified partial position is retained so a stale raw 0% cannot make the UI look closed;
- timed Auto-closing behavior from beta.15 is unchanged: its configured deadline still starts the displayed `closing` phase directly;
- manual Home Assistant Open/Close/Stop still cancels the PED presentation overlay before sending the requested command.

PS25007A command safety is unchanged: exact PS25007 -> PS25007A alias, authenticated-user source tag, single `PED OPEN` publish, no automatic resend and no follow-up movement command.
