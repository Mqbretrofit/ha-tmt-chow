# TMT Chow v1.0.1

Maintenance release fixing the missing Home Assistant integration icon in the published v1.0.0 package.

## Fixed

- Added the local Home Assistant `brand/` assets to the installable release package
- Includes normal and dark integration icons in standard and 2× resolutions

## Notes

There are no functional changes to gate control, MQTT communication, controller parameters, diagnostics or translations.

After updating through HACS, restart Home Assistant. If the old placeholder is still cached in the browser, perform a hard refresh.
