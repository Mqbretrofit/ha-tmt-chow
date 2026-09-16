# TMT Chow v1.0.4-beta.11

## PS19001 same-generation TUTK transport test

The beta.10 hardware probe successfully loaded and initialized the legacy Linux IOTC/RDT libraries, allocated an IOTC session and attempted the PS19001 UID connection, but IOTC 1.13.7.0 stopped with `IOTC_ER_FAIL_SETUP_RELAY` (`-42`) before an RDT channel could be created.

Beta.11 replaces that legacy pair with Linux x86-64 IOTC/RDT 3.1.5.38 libraries. This is the closest publicly available Linux build found to the IOTC 3.1.5.33 generation embedded in the TMT Chow Android application. Both files are pinned to source commit `8a93626da7c12c936d550750e887a020c3049dc0` and verified independently with SHA-256 before they can be installed or loaded.

The native helper, private glibc runtime and probe sequence are otherwise unchanged. The probe remains transport-only: it does not bind or call `RDT_Write` and does not send open, close, stop, status-read, function-read or parameter commands.

The existing AWS/MQTT runtime and control behavior for working controllers is unchanged.
