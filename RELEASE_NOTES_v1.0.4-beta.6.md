# TMT Chow v1.0.4-beta.6

## Diagnostics

- Added an isolated read-only AWS IoT Shadow GET probe to Home Assistant diagnostics for the PS19001 investigation in issue #14.
- Diagnostics now report whether a classic Shadow GET is `accepted`, `rejected`, or receives `no_response`.
- When AWS rejects the Shadow GET, diagnostics include the rejection code and a redacted rejection message.
- The probe uses a temporary MQTT connection only while diagnostics are generated.

## Safety / scope

- The probe subscribes only to `$aws/things/<uuid>/shadow/get/accepted` and `$aws/things/<uuid>/shadow/get/rejected`.
- It publishes only `{}` to `$aws/things/<uuid>/shadow/get`.
- It never subscribes to or publishes `wbt01Rx`, `wbt01Tx`, `/position`, or any gate movement/parameter-write command topic.
- Existing live hub subscriptions, availability rules, gate commands, parameter writes, discovery, and AWS bootstrap behavior are unchanged.

## Tests

- Added regression coverage for accepted, rejected, redacted-rejection, and no-response Shadow GET outcomes.
- Tests verify that the diagnostic probe publishes only the Shadow GET request and never touches gate command topics.
