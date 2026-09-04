# Pedestrian mode command capture test

Diagnostic branch: `pedestrian-capture-test`
Integration version: `1.0.3-beta.1`

This build does **not** send any guessed pedestrian command. It only tries to observe the vendor app's MQTT command traffic on `<uuid>/wbt01Rx` and the controller responses on `<uuid>/wbt01Tx`.

The normal Open / Close / Stop behaviour is unchanged.

## Test procedure

1. Install this branch and restart Home Assistant.
2. Wait until the TMT Chow device is online in Home Assistant.
3. Open **Settings -> System -> Logs**.
4. Search for `TMTDIAG COMMAND_CAPTURE`.
5. Confirm that one of these startup messages is present:
   - `TMTDIAG COMMAND_CAPTURE ENABLED ...` — capture is available.
   - `TMTDIAG COMMAND_CAPTURE SUBSCRIBE_REJECTED ...` — AWS IoT does not permit subscribing to the command topic with this certificate; stop the test and use the fallback capture method.
6. If capture is enabled, clear/ignore older log lines.
7. Open the official TMT Chow app and press the **Pedestrian / Partial open** command exactly once.
8. Wait a few seconds, then export/copy all log lines containing `TMTDIAG COMMAND_CAPTURE`.

Expected useful lines look like:

```text
TMTDIAG COMMAND_CAPTURE RX topic=<uuid>/wbt01Rx payload=...
TMTDIAG COMMAND_CAPTURE TX topic=<uuid>/wbt01Tx payload=...
```

Home Assistant's own commands are marked separately:

```text
TMTDIAG COMMAND_CAPTURE HA_PUBLISH topic=<uuid>/wbt01Rx payload=...
```

That distinction lets us identify a command issued by the vendor app instead of confusing it with a command sent by the integration itself.

## Safety

The additional Rx subscription is diagnostic-only. If AWS IoT rejects that single optional subscription, the client logs `SUBSCRIBE_REJECTED` and continues with all normal required subscriptions instead of failing the integration.
