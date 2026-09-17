# TMT Chow v1.0.4-beta.30

## One diagnostic, usable ACK/NAK map

- Unknown or not-yet-verified controllers still receive the same read-only APK discovery matrix in one Home Assistant diagnostics download: `RS`, `READ STATUS`, `RP,1`, and `READ FUNCTION`.
- Each dialect is now classified separately: `ACK` becomes `working_commands`, `NAK` becomes `rejected_commands`, and anything else stays unresolved.
- The four WBT read probes run one after another so each captured payload belongs to a single request.
- Movement, optional-control, learning and parameter-write commands remain catalogued and are never transmitted.
- `uuid_type=1` OURANOS candidates still test `READ STATUS` and `RS` when the six-digit gate PIN is saved locally.

## What this does not change

- Verified controller runtime, movement, pedestrian and parameter-write paths are unchanged, including PS21053C, PS21050C/D, PS22027, PS22087B/P710U, PS25007A and PS19001.
- A new controller is not automatically controlled from this release. Download diagnostics after updating, then use `working_commands` / `rejected_commands` to add the profile.
