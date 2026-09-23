# TMT Chow v1.0.4-beta.39

## PS24118 / PS24118C standby wake and motion-proof hardening

This beta follows the real-hardware feedback from issue #57 after beta.38.

The beta.38 diagnostic proved that this controller supports both read-only `RS` and `READ STATUS`, while also showing endpoint jitter such as Home Assistant state 100 vs raw RS position 98. Beta.38 could therefore treat endpoint noise as false proof that a missing movement ACK actually caused motion.

Changes in beta.39:

- Before PS24118/PS24118C FULL OPEN and FULL CLOSE, send one serialized best-effort read-only `READ STATUS` preflight to synchronize/wake the controller after standby.
- Movement commands are still sent exactly once and are never automatically retried.
- Endpoint bands are normalized, so values such as 98/100 or 0/2 are treated as the same endpoint.
- Position-only fallback now requires at least a 5% directional change before it can prove real movement.
- A live `is_operating=true` status with the requested direction remains valid strong motion proof.
- Any previous PS24118 post-motion monitor is cancelled before the next intentional movement transaction.
- Diagnostics now include the latest PS24118 command, preflight READ STATUS reply, explicit ACK result, and fallback RS samples.
- Pedestrian Mode and parameter-write safety remain unchanged.

Please re-test:

1. Leave the gate fully Closed for at least 3 minutes.
2. Open from Home Assistant.
3. After it reaches fully Open, close it again from Home Assistant without using the Chow app.
4. Repeat in the opposite direction after at least 3 minutes of standby.
5. Confirm Pedestrian Mode still works.
6. If the second movement still fails, create diagnostics immediately after the failed command, before using the Chow app. The new `ps24118_command_debug` section should now show the exact command/ACK/RS sequence.
