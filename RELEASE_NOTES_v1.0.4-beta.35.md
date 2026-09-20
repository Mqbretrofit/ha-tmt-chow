# TMT Chow v1.0.4-beta.35

## PS17062 ARM64 native support

Issue #53 is the first real-hardware validation of the PS17062 native ARM64 path.

This release adds an isolated Bionic runtime for aarch64 Home Assistant OS and uses the exact ARM64 IOTC/RDT library pair shipped by the TMT Chow Android app. The downloaded APK is used only as a temporary source: the two pinned libraries are extracted, checked by exact size and SHA-256, and the APK is then removed.

Real PS17062 hardware confirmed:

- native TMT IOTC/RDT 3.1.5.33 initialization and connection;
- automatic `READ STATUS` polling;
- live Home Assistant state and position;
- `FULL OPEN` with ACK and live opening/final-open telemetry;
- `FULL CLOSE` through the same native route;
- normal Home Assistant Open / Close / Stop controls on the verified profile;
- the pedestrian `PED OPEN` command operates the gate.

The pedestrian command is available only from a fresh fully closed/stopped state. The reporter noted that the partial-opening distance may be larger than before and will recheck that detail; the command route itself is working.

## PS17062 parameters

The APK-derived 23-parameter UART0 profile is enabled over the same persistent native session.

Parameter changes remain guarded:

- read the complete current frame first;
- send exactly one complete `WRITE FUNCTION` frame;
- never automatically retry a parameter write;
- read the complete frame back afterwards;
- require the readback to match before Home Assistant accepts the change;
- block writes while the gate is moving or when fresh native status is unavailable.

## Existing controllers

PS19001, PS25142, the existing x86-64/glibc native route, AWS/WBT controllers and all previously verified controller-specific behavior remain unchanged.

Regression suite: **154 tests passed** before the release version bump.
