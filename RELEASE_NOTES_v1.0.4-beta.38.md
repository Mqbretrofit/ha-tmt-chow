# TMT Chow v1.0.4-beta.38

## PS24118 / PS24118C command/ACK serialization fix

This beta follows the real-hardware feedback from issue #57 after beta.37.

- Keeps the beta.37 PS24118/PS24118C identity mapping, Pedestrian Mode support and live RS state tracking.
- Serializes every PS24118 read-only `RS` transaction behind the same lock used for movement commands.
- Starts background RS monitoring only after FULL OPEN, FULL CLOSE or PED OPEN has completed its command exchange.
- If a movement ACK is missing, the movement command is **not resent**. Only then are serialized read-only RS probes used to confirm that the requested movement/position actually occurred.
- Periodic and reconnect RS reads are also serialized, so they cannot overlap a movement exchange.
- No parameter-write capability is enabled for PS24118/PS24118C.
- Other controller routes are unchanged.

Please specifically re-test:
1. Closed for at least 3 minutes -> Open from Home Assistant.
2. After it reaches fully Open, issue the next Close from Home Assistant without touching the Chow app.
3. Open for at least 3 minutes -> Close from Home Assistant.
4. After it reaches fully Closed, issue the next Open from Home Assistant without touching the Chow app.
5. Confirm there is no "No ACK FULL OPEN/CLOSE confirmation received" error and Pedestrian Mode still works.
