# TMT Chow v1.0.4-beta.16

## Persistent PS19001 native status session

This beta fixes the repeated native status timeout observed after the first successful PS19001 read. Automatic polling and the **Refresh native gate status** button now reuse one isolated IOTC/RDT connection instead of reconnecting to the gate for every request.

The new session helper remains deliberately status-only. It accepts only the internal `STATUS` and `QUIT` control words and its sole native write path constructs the fixed APK-compatible `READ STATUS;src=P9999999` request. It has no arbitrary payload input and contains no open, close, stop, function-read or parameter-write command. The helper binary is integrity-pinned and runs outside Home Assistant Core through the same private glibc runtime.

If a status read times out, returns malformed output or reports a dead transport, the integration terminates that helper. A later scheduled or manual refresh can then establish a clean session. Unloading or reloading the integration also closes the session. Diagnostics expose only whether the session is connected; the UID and PIN remain protected.

The existing one-shot `tmt_chow.ouranos_probe` diagnostic action is unchanged. AWS/MQTT movement commands, discovery, other controller families and parameter handling are unchanged.
