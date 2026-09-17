# TMT Chow for Home Assistant

[![Release](https://img.shields.io/badge/release-v1.0.4--beta.30-orange)](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.30)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://www.hacs.xyz/)
[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Mqbretrofit&repository=ha-tmt-chow&category=integration)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-EA4AAA?logo=githubsponsors)](https://github.com/sponsors/Mqbretrofit)

Unofficial Home Assistant custom integration for **TMT Automation / TMT Chow (ChowHUB)** gate controllers.

The integration brings supported TMT Chow gates into Home Assistant as native entities, allowing gate control, pedestrian / partial opening, live status monitoring, controller configuration and automation from the Home Assistant UI.

## ❤️ Support development

TMT Chow for Home Assistant is an independent open-source community project. Continued development includes protocol research, controller mapping, diagnostics, regression testing and real-hardware validation.

If this integration is useful to you, you can support continued development through **[GitHub Sponsors](https://github.com/sponsors/Mqbretrofit)**. For sponsored feature requests, priority development and additional support options, see **[SUPPORT.md](SUPPORT.md)**.

> **Current release:** [`v1.0.4-beta.30`](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.30) (pre-release)
>
> Last non-beta release: `v1.0.3`

## What's new in v1.0.4-beta.30

- The unknown-controller diagnostic still tests every safe APK read dialect in one download: `RS`, `READ STATUS`, `RP,1`, and `READ FUNCTION`.
- Each dialect is now classified as `ACK` (`working_commands`), `NAK` (`rejected_commands`), or unresolved, so a rejected line stays in the JSON instead of looking like a working command.
- The four WBT read probes run one after another so each captured payload belongs to a single request.
- Movement, relay, learning, reset and parameter-write commands remain catalogued and are never sent.
- Verified controller runtime, pedestrian and parameter-write paths are unchanged.
