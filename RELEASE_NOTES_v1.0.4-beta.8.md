# TMT Chow v1.0.4-beta.8

## PS19001 / OURANOS diagnostics

- Adds a Home Assistant-hosted read-only OURANOS / ThroughTek IOTC+RDT connectivity probe for the PS19001 investigation in issue #14.
- The probe runs directly from Home Assistant through the new `tmt_chow.ouranos_probe` action; an external Linux/WSL machine is no longer required for this stage.
- Architecture selection supports Home Assistant hosts reporting `aarch64`/`arm64`, `x86_64`/`amd64`, and `armv7`.
- The native TUTK library is not loaded into the Home Assistant Core process. It runs in a short-lived child Python process so a native crash cannot take down Home Assistant Core.
- The architecture-specific library is pinned to a fixed upstream commit and its Git blob SHA is verified before execution.

## What the probe reports

- whether the native library could be downloaded and verified;
- whether it could be loaded on the Home Assistant host;
- presence of the required IOTC and RDT symbols;
- IOTC initialization and session allocation result;
- whether the 20-character OURANOS device identifier establishes an IOTC session;
- whether an RDT channel can be created;
- whether any data arrives during a short passive RDT read window.

The response also preserves useful native error codes such as unsupported ABI, missing SDK licensing, device offline/not listening, or missing RDT symbols instead of masking them as a generic connectivity error.

## Safety / scope

This is still a transport-only diagnostic probe. It does **not**:

- request AWS IoT certificates or policies;
- connect to MQTT;
- bind or call `RDT_Write`;
- send `FULL OPEN`, `FULL CLOSE`, `STOP`, or `PED OPEN`;
- send `RS` or `READ FUNCTION`;
- read or write gate parameters through an application command.

After a successful RDT channel creation it performs only a short passive `RDT_Read` window. The raw 20-character device identifier is not included in the returned diagnostic data.

## Existing controllers

The existing AWS/WBT runtime and control behavior for already-working controllers is unchanged by this diagnostic addition.
