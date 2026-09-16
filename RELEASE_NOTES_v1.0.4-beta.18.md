# TMT Chow v1.0.4-beta.18

This beta changes endpoint tolerance so Home Assistant does not declare a moving gate fully closed/open several percent too early.

## What changed

- Dedicated live `/position` telemetry is now kept exact while the motor is moving.
- `5%`, `4%`, `2%`, etc. remain real live values and the cover continues to show `closing` while movement is active.
- `95%` to `99%` remain real live values and the cover continues to show `opening` while movement is active.
- The historical endpoint tolerance is preserved only after the controller reports that the motor has stopped:
  - stopped `0-5%` is accepted as fully closed (`0%`);
  - stopped `95-100%` is accepted as fully open (`100%`).
- Exact live `0%` and `100%` still finish movement immediately, preserving existing endpoint behavior.
- The existing stale stopped-DEV-STATUS direction guard is preserved.

## Why

Some controllers have previously stopped physically closed while reporting a residual `1-2%`, so removing endpoint tolerance entirely would reintroduce the old stuck-near-zero problem. The previous implementation, however, applied the tolerance during movement and therefore could show `closed` already at `5%` while the gate was still physically travelling.

Beta.18 keeps both behaviors correct: exact live travel percentages during motion, tolerant endpoint normalization only after stop.

No movement-command, PED command, ACK, or retry behavior is changed by this beta.
