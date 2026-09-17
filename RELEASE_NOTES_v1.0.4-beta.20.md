# TMT Chow v1.0.4-beta.20

This beta fixes PS19001 parameter discovery and writes using the exact frame returned by real hardware.

## Fixed

- PS19001 now exposes the 19 real controller parameters labelled `1` through `J`.
- The four generated P190 current-table helpers are no longer treated as separate wire fields.
- JSON-wrapped native `ACK READ FUNCTION` responses are parsed strictly and safely.
- Normal, limit-switch and Hall Sensor motor modes use their matching APK-derived current option tables.

## Write safety

- Every change starts with a fresh complete parameter read.
- The integration sends one exact full-frame `WRITE FUNCTION,1...J` request and never retries it automatically.
- Success requires a complete 19-slot readback matching the requested frame.
- The native helper rejects the obsolete zero-based 23-slot format and all malformed or out-of-order fields.

PS19001 open, close, stop, pedestrian opening and live cover status are unchanged.
