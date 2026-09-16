# TMT Chow v1.0.4-beta.10

## PS19001 probe download fix

The first beta.9 hardware test confirmed that both pinned IOTC/RDT libraries were cached and passed their integrity checks, but the native helper did not start because the verified private glibc archive is 52,484,557 bytes while the download safety ceiling was 32 MiB.

Beta.10 raises only that ceiling to 64 MiB. The pinned SHA-512 verification, restricted extraction, helper isolation and read-only transport behavior are unchanged. The next probe run can now proceed to native IOTC/RDT initialization.

The existing AWS/MQTT runtime and control behavior for working controllers is unchanged.
