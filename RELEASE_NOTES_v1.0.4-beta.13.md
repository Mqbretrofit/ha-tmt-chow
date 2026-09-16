# TMT Chow v1.0.4-beta.13

## PS19001 read-only native status request

Beta.11 confirmed that Home Assistant can establish the PS19001's native ThroughTek IOTC/RDT transport. Beta.13 adds the next deliberately limited step: one read-only gate-status request using the exact framing observed in TMT Chow 3.1.4. It supersedes beta.12, whose release archive lost the native helper's executable file mode during API publication.

The `tmt_chow.ouranos_probe` action now asks for the gate's six-digit TMT Chow PIN. The PIN is used only in memory to apply the app's repeating XOR encoding, is passed to the isolated native helper over standard input, is not stored in the integration, and is not returned in diagnostics. The decoded response also redacts the app source identifier, UID and any matching PIN value.

The helper constructs a fixed `READ STATUS` UART request internally and calls `RDT_Write` exactly once. It has no arbitrary-command input and contains no open, close, stop, parameter-read or parameter-write command. Existing AWS/MQTT controllers and their control paths are unchanged.

The regression suite includes a simulated IOTC/RDT peer that verifies the encrypted request byte for byte, returns an encrypted `ACK STATUS` response, and checks both decoding and sensitive-value redaction.
