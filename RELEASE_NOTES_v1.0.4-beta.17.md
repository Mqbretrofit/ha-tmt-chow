# TMT Chow v1.0.4-beta.17

This test release completes the native PS19001 integration for the confirmed 20-character OURANOS/TUTK device route.

## Added

- Full open, full close, stop and pedestrian opening through the persistent native connection
- Live native status polling and manual refresh
- All 23 PS19001 model parameters as Home Assistant number/select entities
- Native parameter read and safe full-frame parameter write

## Safety

- Movement commands and parameter writes are sent exactly once and are never automatically retried
- Every parameter change starts with a fresh complete read and ends with mandatory readback verification
- The native helper accepts only fixed gate operations and a strictly validated PS19001 UART0 parameter frame
- Existing AWS/MQTT controllers remain on their previous code paths

Please test movement first while the gate area is visible and clear. Then change one harmless parameter, verify it in the TMT Chow app, and report the full Home Assistant error and diagnostics if any operation fails.
