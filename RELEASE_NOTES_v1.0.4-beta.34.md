# TMT Chow v1.0.4-beta.34

## PS25142 RP,1 parameter availability fix

Issue #51 confirmed that the PS25142 controller was already returning the correct 18-value UART V3.0 parameter frame:

`ACK RP,1:1,8,0,3,0,1,5,0,0,0,0,2,3,0,0,0,1,1`

The beta.33 decoder could reject this specific native response shape when the UART reply arrived inside the serialized OURANOS JSON envelope and ended with escaped CR/LF without a `;src=` suffix. Diagnostics then counted commas in the JSON wrapper, which produced the misleading 23-token report.

Beta.34 fixes the parsing layer:

- unwrap native/helper JSON envelopes first;
- extract the UART `DATA` text;
- parse the actual `ACK RP,1` body;
- validate exactly 18 Proposal-B values;
- expose those values to the Home Assistant parameter entities;
- report the correct 18-token frame in diagnostics.

Regression tests cover the exact issue #51 payload, including the nested native response envelope.

No PS25142 movement/status behavior is changed in this release. Existing controller-specific routes remain unchanged.
