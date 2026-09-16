# TMT Chow v1.0.4-beta.17

## PED state fix for Auto-closing OFF and external close

Real-device testing showed one remaining presentation-state problem when `Auto-closing = OFF`: after the pedestrian opening finished, repeated controller status frames could report `closing` even while the gate was physically stationary at the partial-open position. Because the beta.16 state machine allowed repeated status direction bits to prove closing, Home Assistant could switch from `open` to `closing` and disable the normal Close control incorrectly.

Beta.17 changes only this state/presentation path:

- once a PED cycle has received dedicated `/position` telemetry, controller status direction bits alone can no longer change the displayed state from `open` to `closing`;
- two consecutive decreasing dedicated `/position` updates still prove real closing;
- controllers without a useful `/position` topic retain the repeated-status fallback;
- repeated closing status is still tracked as corroborating evidence without changing the display state;
- if the gate is then closed externally from the TMT app or a physical remote and a fresh stopped `0%` status arrives, the PED overlay is cleared to `closed` even if no new `/position` update was published;
- when the display is already genuinely `closing`, a fresh live `0%` or a fresh stopped `0%` status newer than the closing live sample can complete the cycle;
- timed Auto-closing behavior from beta.15 remains unchanged;
- no movement-command behavior or PS25007A PED command safety logic is changed in this beta.

This directly covers the reproduced sequence: PED with Auto-closing OFF -> partial-open and stationary -> misleading `closing` status -> vendor-app Close -> physically closed -> HA must end as `closed`, not remain stuck on `closing`.