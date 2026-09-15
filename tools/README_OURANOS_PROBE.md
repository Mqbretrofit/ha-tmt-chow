# TMT Chow OURANOS / TUTK connectivity probe

`tools/tmt_chow_ouranos_probe.py` is a standalone **read-only transport probe** for TMT Chow devices that are returned by the account API with `uuid_type: "1"` (OURANOS backend).

It is intentionally separate from the Home Assistant runtime. Its purpose is to answer one question before an OURANOS transport is added to the integration:

> Can the device's 20-character TUTK/IOTC UID establish an IOTC session and an RDT channel from Linux?

## Safety

Probe v0.1:

- logs in to TMT Chow and reads the device list;
- selects only `uuid_type == "1"` devices;
- opens an IOTC connection and attempts `RDT_Create`;
- optionally performs a short **passive** `RDT_Read` window;
- **does not bind or call `RDT_Write`**;
- sends no `FULL OPEN`, `FULL CLOSE`, `STOP`, `PED OPEN`, `RS`, `READ FUNCTION`, or parameter-write command;
- does not request AWS IoT certificates/policies and does not connect to MQTT;
- does not write the TMT username, password, access token, or raw device UID to the report.

The raw UID is used in memory only for `IOTC_Connect_ByUID_Parallel()` and is represented in the JSON report by a short SHA-256 marker plus its length.

## Requirements

- Python 3.11+ recommended.
- Linux is recommended for the first test.
- Native ThroughTek libraries matching the host architecture:
  - `libIOTCAPIs.so`
  - `libRDTAPIs.so`

For **Linux x86_64**, the probe can download the pinned public ThroughTek starter-kit libraries itself and verify their Git blob SHA before loading them.

For another Linux architecture, provide compatible native libraries with `--lib-dir`.

## Run the offline self-test first

From the repository root:

```bash
python tools/tmt_chow_ouranos_probe.py --self-test
```

Expected result:

```text
Self-test OK: OURANOS selection/privacy/integrity checks passed.
Safety: probe v0.1 contains no RDT_Write call path.
```

The self-test does not contact TMT or ThroughTek.

## Linux x86_64: run the connectivity probe

```bash
python tools/tmt_chow_ouranos_probe.py --download-sdk
```

The script prompts for:

```text
TMT Chow username:
TMT Chow password:
```

The credentials are used for the login request only and are not written to the output file.

The default output is:

```text
tmt_chow_ouranos_probe.json
```

Please attach that JSON to the relevant GitHub issue. Do not post screenshots containing credentials.

## Using your own native libraries

```bash
python tools/tmt_chow_ouranos_probe.py --lib-dir /path/to/tutk/linux/libs
```

The directory must contain both `libIOTCAPIs.so` and `libRDTAPIs.so`. Their SHA-256 fingerprints are recorded in the report so test results can be compared without redistributing the binaries.

## Multiple OURANOS devices

The first matching device is selected by default. To test another one:

```bash
python tools/tmt_chow_ouranos_probe.py --download-sdk --device-index 1
```

No raw UID is printed or written to the report.

## Advanced diagnostic options

Defaults are deliberately conservative:

```text
IOTC connect timeout: 25 s
RDT channel:          0
RDT create timeout:   10000 ms
Passive read window:  2 s
```

They can be changed without enabling writes:

```bash
python tools/tmt_chow_ouranos_probe.py \
  --download-sdk \
  --channel 0 \
  --connect-timeout 25 \
  --rdt-timeout-ms 10000 \
  --listen-seconds 2
```

A successful first-stage result should show:

```json
"iotc_connected": true,
"rdt_connected": true
```

Even if `passive_read_count` remains `0`, a successful RDT channel is enough to move to the next protocol-research stage. Probe v0.1 intentionally does not transmit an application payload.

## Windows users

The automatic SDK path in v0.1 is for Linux x86_64. On a normal x86_64 Windows PC, the simplest way to run the first probe is an Ubuntu/WSL2 environment with Python installed, then run the Linux command above from a clone/copy of this repository.

Do not use the Android `.so` files extracted from the TMT Chow APK on normal Linux: those are Android-native binaries, not generic Linux libraries.
