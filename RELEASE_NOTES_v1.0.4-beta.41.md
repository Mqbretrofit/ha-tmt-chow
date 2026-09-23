# TMT Chow v1.0.4-beta.41

## PS24118 / PS24118C vendor UART-v1 source-tag test

This beta follows the two beta.39 hardware diagnostics from issue #57 and a direct comparison with the extracted TMT Chow Android command path.

The hardware captures proved that the failed second FULL OPEN/FULL CLOSE is explicitly ACKed while the gate remains stationary. Separately, the vendor app evidence shows that normal UART-v1 commands use a per-user source tag in the form `P%07X(user_id)`, while the affected Home Assistant entry still uses the default/privacy tag `P9999999`.

Beta.41 tests that concrete difference and supersedes the beta.40 endpoint re-arm workaround for PS24118/PS24118C.

### Changes

- Only configured PS24118 requests an additional **optional** MQTT subscription to its own `wbt01Rx` command topic.
- While the config entry still uses `P9999999`, Home Assistant learns the first non-default vendor-app `src=P.......` tag observed on that topic.
- The learned tag is persisted in the config entry and reused after reload/restart.
- FULL OPEN, FULL CLOSE and PED OPEN then use the same vendor-shaped `c=<command>;src=<tag>` envelope.
- The beta.40 injected same-endpoint re-arm movement is removed.
- The beta.39 READ STATUS movement preflight is removed.
- Movement commands remain **exactly once** with no automatic resend.
- Serialized read-only RS monitoring remains enabled.
- Endpoint jitter such as 98/100 or 0/2 is still not accepted as proof of movement.
- If the AWS policy rejects the optional RX observation subscription, required existing MQTT subscriptions stay active.
- Diagnostics add `ps24118_source_tag_debug` and record whether the current movement used the default or learned/configured vendor tag, without exposing the learned numeric tag in the dedicated debug fields.
- Pedestrian Mode and all non-PS24118 controller routes are unchanged.

### Required test sequence

1. Install **v1.0.4-beta.41** and restart Home Assistant.
2. Keep Home Assistant running and open the official Chow app.
3. Send **one normal Open or Close command from the official Chow app**. This gives beta.41 one opportunity to observe and persist the app's source tag.
4. Wait for Home Assistant to reconnect/reload if necessary.
5. Do not use the Chow app again for the remaining test.
6. Leave the gate at an endpoint for at least 3 minutes.
7. Send the first movement from Home Assistant and let it reach the opposite endpoint.
8. Send the second opposite movement from Home Assistant.
9. Repeat in the other direction.
10. Confirm Pedestrian Mode still works.

If the second movement still fails, create diagnostics immediately after the failed Home Assistant command. The new source-tag diagnostics will show whether a non-default vendor tag was actually learned and used.
