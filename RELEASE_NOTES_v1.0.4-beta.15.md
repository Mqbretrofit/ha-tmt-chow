# TMT Chow v1.0.4-beta.15

## PS19001 native status stability and manual refresh

Beta.14 confirmed that the native PS19001 response can set the Home Assistant cover to the correct closed state. It also exposed a stability problem: the integration opened a new IOTC/RDT session every five seconds and marked the cover unavailable after only 30 seconds without another successful response.

Beta.15 reduces that connection pressure. Successful reads are scheduled 15 seconds apart, failed reads retry after 60 seconds, and automatic and manual reads are serialized so one gate cannot start overlapping native helper sessions. The last valid native state now keeps the cover available for up to 15 minutes instead of 30 seconds.

A new **Refresh native gate status** button requests one immediate status-only read and remains available even if the cover is currently unavailable. Diagnostics now include the last result, attempt and success timestamps, status age, consecutive failure count, configured timing and whether a refresh is running. The PIN remains redacted.

The native safety boundary is unchanged. The helper can construct only the fixed `READ STATUS` request and contains no native open, close, stop, function-read, parameter-read or parameter-write command. Existing AWS/MQTT controllers and command paths are unchanged.
