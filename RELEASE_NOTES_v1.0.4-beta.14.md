# TMT Chow v1.0.4-beta.14

## Automatic PS19001 native cover status

The real-hardware beta.13 result confirmed an end-to-end response from the PS19001 gate: `ACK STATUS:PED CLOSED,0`. Beta.14 turns that proven read-only path into an opt-in Home Assistant cover status source.

For a confirmed PS19001 gate with a 20-character UID, open **Settings → Devices & services → TMT Chow → Configure**, enter the six-digit gate PIN, and save. The integration then periodically runs the isolated native helper and maps the returned position and opening/closing state onto the existing cover entity. Clear the PIN field to disable native polling.

The PIN is stored only in the local Home Assistant config entry, uses a password-style field, is passed to the helper through standard input, and is redacted from diagnostics. The native response is also sanitized before it reaches Home Assistant.

This beta remains status-only. The helper can construct only the fixed `READ STATUS` request and has no arbitrary-command input; it contains no native open, close, stop, function-read, parameter-read or parameter-write command. Existing AWS/MQTT controllers and all existing command paths are unchanged. Failed native reads use a 30-second retry delay, and stopping or reloading the integration terminates an active helper safely.
