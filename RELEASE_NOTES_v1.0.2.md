# TMT Chow v1.0.2

## What's new

- Multi-controller support based on TMT Chow 3.1.4 and gatePRO Smart! 1.0.0 controller definitions.
- Per-model controller family and capability detection.
- Per-model parameter schemas for 217 gate controller models.
- Per-model UART parameter read/write codecs and skip-list handling.
- Home Assistant `select` entities for discrete parameters.
- Home Assistant `number` entities for numeric parameters.
- Mandatory parameter read-back verification after writes.
- PS21053 / PS21053C backward compatibility retained.
- `product_type` values such as 112 and 118 are handled independently from the concrete controller model.
- Unknown/API-only controllers are not assigned guessed parameter schemas or optional controls.

## Notes

PS21053/PS21053C has been validated on real hardware. Other mapped controller models are implemented from the vendor APK/XAPK definitions and should be treated as APK-derived until independently validated on matching hardware.
