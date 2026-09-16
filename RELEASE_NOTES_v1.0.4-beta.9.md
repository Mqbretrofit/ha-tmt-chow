# TMT Chow v1.0.4-beta.9

## Corrected PS19001 / OURANOS transport probe

Beta 9 replaces the incompatible combined TUTK 4.2.x library used by the previous probe. Analysis of the original TMT Chow 3.1.4 APK confirmed that PS19001 uses separate IOTC and RDT libraries, calls `IOTC_Initialize2(0)` without an external SDK licence key, connects the 20-character UID in parallel, then opens RDT channel 0 with a 5000 ms timeout.

The integration now downloads pinned legacy Linux x86-64 IOTC 1.13.7.0 and RDT 1.7.4.0 libraries that expose the same separate-library, licence-free API shape. Both the SDK archive and extracted libraries are verified by SHA-256 before execution. This is still an experimental compatibility probe: only a response from matching PS19001 hardware can establish whether this Linux SDK generation can reach the controller.

## Home Assistant operation

- The probe remains part of the normal TMT Chow integration; no separate add-on is required.
- It currently supports x86-64 Home Assistant installations.
- The native libraries run in a short-lived helper process using a private, integrity-checked glibc runtime, isolated from Home Assistant Core.
- The first run downloads and caches the pinned SDK archive and private runtime under Home Assistant's `.storage` directory.
- Run **Developer tools → Actions → TMT Chow: OURANOS transport probe** and paste the complete response JSON into issue #14. Do not post the PS19001 UUID publicly.

## Safety and existing controllers

The probe is transport-only. It binds no `RDT_Write` symbol and sends no open, close, stop, status-read, function-read or parameter payload. The established AWS/MQTT runtime and control behavior for existing WBT controllers is unchanged.
