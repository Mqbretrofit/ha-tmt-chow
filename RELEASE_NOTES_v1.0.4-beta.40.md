# TMT Chow v1.0.4-beta.40

## PS24118 / PS24118C guarded endpoint re-arm workaround

This beta follows the two beta.39 real-hardware diagnostics from issue #57.

The new evidence is definitive: on the failed second movement the controller receives and explicitly ACKs FULL OPEN/FULL CLOSE, but the motor remains stopped at the previous endpoint. One capture also reports the contradictory logical state `ACK STATUS:FULL CLOSED,99` while the gate is physically open.

The official TMT Chow APK flow was also checked. Ordinary Open/Close still sends a single FULL OPEN/FULL CLOSE command; there is no hidden automatic wake sequence. The original issue report, however, documents a working manual recovery in the official app: press the already-reached direction once more, then press the opposite direction.

Beta.40 mirrors that proven recovery only under tightly guarded PS24118/PS24118C conditions:

- Detect a full movement issued after at least 180 seconds without another full movement command.
- Mark the reached endpoint for one possible re-arm before the next opposite movement.
- Also trigger the workaround when READ STATUS explicitly contradicts the proven physical endpoint.
- Before an injected re-arm, require a fresh read-only RS proving the gate is stationary at the matching endpoint.
- At an open endpoint, the re-arm is one FULL OPEN; at a closed endpoint, it is one FULL CLOSE.
- Require the explicit ACK for that re-arm, wait 350 ms, then send the user's requested opposite command exactly once.
- Never automatically retry either the re-arm or the requested movement.
- If the user manually presses the same endpoint direction, that command itself consumes the pending re-arm; no duplicate command is injected.
- Pedestrian Mode, parameter safety, and every non-PS24118 controller route are unchanged.
- Diagnostics keep the re-arm reason, endpoint-proof RS, re-arm ACK, requested command ACK, and fallback evidence.

Please test both directions after at least 3 minutes of standby. If either second movement still fails, generate diagnostics immediately before using the Chow app.
