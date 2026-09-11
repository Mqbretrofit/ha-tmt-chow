# TMT Chow for Home Assistant

[![Release](https://img.shields.io/badge/release-v1.0.3-blue)](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.3)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://www.hacs.xyz/)
[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Mqbretrofit&repository=ha-tmt-chow&category=integration)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-EA4AAA?logo=githubsponsors)](https://github.com/sponsors/Mqbretrofit)

Unofficial Home Assistant custom integration for **TMT Automation / TMT Chow (ChowHUB)** gate controllers.

The integration brings supported TMT Chow gates into Home Assistant as native entities, allowing gate control, pedestrian / partial opening, live status monitoring, controller configuration and automation from the Home Assistant UI.

## ❤️ Support development

TMT Chow for Home Assistant is an independent open-source community project. Continued development includes protocol research, controller mapping, diagnostics, regression testing and real-hardware validation.

If this integration is useful to you, you can support continued development through **[GitHub Sponsors](https://github.com/sponsors/Mqbretrofit)**. For sponsored feature requests, priority development and additional support options, see **[SUPPORT.md](SUPPORT.md)**.

> **Current stable release:** `v1.0.3`

## What's new in v1.0.3

- Added a dedicated **Pedestrian opening** button for supported controller models using the vendor `PED OPEN` command.
- Added safe ACK-loss handling for `FULL OPEN`, `FULL CLOSE` and `PED OPEN`: fresh matching telemetry can confirm execution, but movement commands are never automatically resent.
- Fixed stale stopped `DEV STATUS` updates that could make a physically closed gate appear open in Home Assistant.
- Hardened endpoint state tracking so a late stale status packet cannot flip a just-closed gate back to open, or a just-opened gate back to closed.
- Added direct APK-derived support for the verified TMT account `PS21050` / live `PS21050D` controller pair.
- Added exact 20-value `RP,1` / `WP,1` PS21050D parameter handling derived from TMT Chow 3.1.4, including the vendor normal/Hall overcurrent option tables.
- PS21050D parameter writes use a fresh read → single-field change → one write → full read-back verification sequence. Parameter writes are never automatically retried.
- Extended diagnostics with configured/live controller identity, parameter profile, codec and write-verification information.
- Added GitHub Actions regression testing.

## Features

- Open, close and stop the gate from Home Assistant
- Pedestrian / partial gate opening on supported controllers
- Live gate state and gate position
- Protection against late stale stop-status updates at fully open/closed endpoints
- Battery monitoring
- Multi-controller support with APK/XAPK-derived model detection and capabilities
- Model-specific parameter schemas for 217 concrete gate-controller models
- Model-specific UART parameter read/write codecs
- Read supported ChowHUB controller parameters
- Change supported controller parameters directly from Home Assistant
- Mandatory read-back verification after parameter writes
- Discrete parameters exposed as `select` entities and numeric parameters as `number` entities
- Dedicated `button` entity for supported pedestrian-opening control
- Home Assistant UI-based setup through Config Flow
- Diagnostics support
- Cloud-push / MQTT runtime connection
- 23 interface translations
- Entities can be used in Home Assistant automations, scripts and dashboards

## Controller parameters

The integration exposes supported ChowHUB settings as Home Assistant entities, including:

- Operation direction
- Automatic closing time
- Safety device mode
- Operation speed
- Deceleration point
- Deceleration speed
- Overcurrent limit
- Pedestrian mode
- Flashing light
- Overcurrent reaction
- Main operation button
- Pedestrian / partial-opening button
- External device button
- Photocell activation
- Second photocell activation
- STOP input function
- Gate operation sequence

Parameter availability, order and wire encoding are selected from the detected controller model. Parameter changes are written back to the controller and then read again so Home Assistant only reflects the controller's confirmed state.

`PS21053` / `PS21053C` parameter handling has been validated on real hardware. `PED OPEN` has also been verified on a real `PS21053C` controller with `ACK PED OPEN` and partial-position feedback.

For `PS21050D`, a real installation has verified the account/live identity pair (`PS21050` account model, `PS21050D` live `DEV INFO`), the 20-value parameter frame, Home Assistant parameter entities and the corrected open/closed state handling. TMT Chow 3.1.4 contains the `PS21050` product implementation and no separate `PS21050D` implementation, so the integration uses the vendor PS21050 definitions only for this exact verified alias. The PS21050D write format and option tables are APK-derived and protected by mandatory read-before-write and read-back verification.

The remaining mapped controller models are implemented from the vendor TMT Chow 3.1.4 and gatePRO Smart! 1.0.0 APK/XAPK definitions and should be considered APK-derived until independently validated on matching hardware. Unknown/API-only controller models are not assigned guessed parameter schemas or optional capabilities.

For the complete PS21050D vendor mapping and protocol notes, see [`PS21050D_APK_MAPPING.md`](PS21050D_APK_MAPPING.md).

## Supported languages

The integration currently includes **23 translations**:

Bulgarian, Croatian, Czech, Danish, Dutch, English, Finnish, French, German, Greek, Hungarian, Italian, Norwegian Bokmål, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Spanish, Swedish, Turkish and Ukrainian.

Home Assistant uses the integration translation resources for entity names, selectable values, setup messages and user-facing errors.

## Installation

### HACS custom repository

1. Open **HACS** in Home Assistant.
2. Open the HACS menu and choose **Custom repositories**.
3. Add:

   ```text
   https://github.com/Mqbretrofit/ha-tmt-chow
   ```

4. Select **Integration** as the repository type.
5. Install **TMT Chow**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration**.
8. Search for **TMT Chow**.

### Manual installation

1. Download the latest release from the GitHub Releases page.
2. Copy:

   ```text
   custom_components/tmt_chow
   ```

   into:

   ```text
   /config/custom_components/tmt_chow
   ```

3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → TMT Chow**.

## Configuration

Configuration is performed entirely from the Home Assistant UI.

During setup, sign in with your TMT Chow account and select the gate you want to add. The account password is used during authentication and is not stored by the integration after setup.

The integration receives the device credentials required for the TMT Chow cloud connection and uses them to maintain the runtime MQTT connection.

## Home Assistant entities

A configured gate can provide:

- A `cover` entity for gate control and position
- A pedestrian-opening `button` on supported controllers
- A battery `sensor`
- `select` entities for supported discrete controller parameters
- `number` entities for supported numeric controller parameters

The exact entity IDs are generated by Home Assistant and depend on the configured device name and controller capabilities.

## Automations

Because the gate is exposed as a standard Home Assistant cover entity, it can be used in normal Home Assistant automations and scripts.

Example:

```yaml
alias: Close gate at night
triggers:
  - trigger: time
    at: "22:30:00"
conditions:
  - condition: state
    entity_id: cover.my_gate
    state: open
actions:
  - action: cover.close_cover
    target:
      entity_id: cover.my_gate
```

Replace `cover.my_gate` with the entity ID created for your gate.

## Diagnostics

Home Assistant diagnostics are supported and can be downloaded from the integration page for troubleshooting.

Sensitive authentication material is redacted by Home Assistant diagnostics where applicable.

## Updates

Stable releases are published on the GitHub Releases page:

https://github.com/Mqbretrofit/ha-tmt-chow/releases

Current stable release: **v1.0.3**

## Disclaimer

This is an **independent community project** and is not an official TMT Automation product.

A gate is a moving physical system. Use automations responsibly and keep all required photocells, safety inputs, obstacle detection and other physical safety devices enabled, correctly installed and tested.

---

# Magyar

Nem hivatalos Home Assistant integráció **TMT Automation / TMT Chow (ChowHUB)** kapuvezérlőkhöz.

## ❤️ A fejlesztés támogatása

A TMT Chow for Home Assistant egy független, nyílt forráskódú közösségi projekt. A folyamatos fejlesztés része a protokollkutatás, a vezérlők feltérképezése, a diagnosztika, a regressziós tesztelés és a valódi hardveres ellenőrzés.

Ha hasznos számodra az integráció, a fejlesztést a **[GitHub Sponsors](https://github.com/sponsors/Mqbretrofit)** oldalon támogathatod. Támogatott funkciókéréshez, kiemelt fejlesztéshez és további lehetőségekhez lásd a **[SUPPORT.md](SUPPORT.md)** fájlt.

> **Jelenlegi stabil verzió:** `v1.0.3`

## Újdonságok a v1.0.3-ban

- Új **Pedestrian opening / gyalogos nyitás** gomb a támogatott vezérlőkhöz a gyári `PED OPEN` paranccsal.
- Biztonságos ACK-hiány kezelés `FULL OPEN`, `FULL CLOSE` és `PED OPEN` parancsoknál: friss, megfelelő telemetria igazolhatja a végrehajtást, de a mozgási parancsot az integráció soha nem küldi újra automatikusan.
- Javítva az a hiba, amikor egy későn érkező, elavult `DEV STATUS` miatt a fizikailag bezárt kapu Home Assistantban ismét nyitottnak látszhatott.
- A teljesen nyitott/zárt végállapot után érkező elavult státuszcsomag már nem fordíthatja vissza tévesen az `Open` / `Closed` állapotot.
- Közvetlen, APK-ból visszafejtett támogatás a `PS21050` fiókmodell / `PS21050D` élő vezérlő pároshoz.
- Pontos, 20 értékes `RP,1` / `WP,1` PS21050D paraméterkezelés a TMT Chow 3.1.4 alapján, beleértve a normál/Hall túláram opciókat.
- PS21050D paraméterírásnál friss olvasás → egy mező módosítása → egyetlen írás → teljes visszaolvasás és ellenőrzés történik; automatikus írásismétlés nincs.
- Bővített diagnosztika és GitHub Actions regression tesztek.

## Fő funkciók

- Kapu nyitása / zárása / megállítása Home Assistantból
- Gyalogos / részleges nyitás a támogatott vezérlőkön
- Élő kapuállapot és pozíció
- Védelem a végállapot után érkező elavult stop-státuszok ellen
- Akkumulátor szenzor
- Több vezérlőtípus automatikus felismerése és modellenkénti képességkezelés
- 217 konkrét kapuvezérlő-modellhez modellenkénti paraméterséma
- Modellenkénti UART paraméter-kódolás és -dekódolás
- Támogatott ChowHUB vezérlőparaméterek kiolvasása
- Támogatott paraméterek módosítása Home Assistantból
- Kötelező visszaolvasás és ellenőrzés minden paraméterírás után
- Választható paraméterek `select`, numerikus paraméterek `number` entitásként
- Külön `button` entitás a támogatott gyalogos nyitáshoz
- Grafikus telepítés a Home Assistant felületéről
- Diagnosztika
- Cloud push / MQTT kapcsolat
- 23 nyelv támogatása
- Használható automatizálásokban, scriptekben és dashboardokon

## Vezérlő- és paramétertámogatás

A v1.0.3 a TMT Chow 3.1.4 és a gatePRO Smart! 1.0.0 APK/XAPK vezérlődefiníciói alapján modellenként kezeli a kapuvezérlők képességeit, paraméterlistáját és UART paraméterprotokollját. A támogatási katalógus 217 konkrét kapuvezérlő-modellhez tartalmaz paramétersémát és protokollprofilt.

A `PS21053` / `PS21053C` paraméterkezelése valódi hardveren validálva lett. A `PED OPEN` parancs `PS21053C` vezérlőn szintén valódi hardveren ellenőrzött: `ACK PED OPEN` válasszal és részleges pozíció-visszajelzéssel.

A `PS21050D` esetén valódi telepítésen igazolt a `PS21050` fiókmodell / `PS21050D` élő `DEV INFO` páros, a 20 értékes paraméterkeret, a Home Assistant paraméter-entitások és a javított nyitott/zárt állapotkezelés. A TMT Chow 3.1.4 APK-ban külön PS21050D implementáció nincs; az integráció ezért csak ennél a pontosan igazolt alias-párnál használja a gyári PS21050 definíciókat. A paraméterírás formátuma és opciótáblái APK-ból származnak, az írást pedig kötelező előolvasás és visszaellenőrzés védi.

A többi leképezett modell támogatása az APK/XAPK gyári definícióiból származik, ezért az adott hardveren történő külön validálásig APK-alapú támogatásnak tekintendő. Ismeretlen vagy csak API-ból látott vezérlőhöz az integráció nem rendel találgatással paramétersémát vagy opcionális vezérlési képességet.

A teljes PS21050D paraméter- és protokolltérkép: [`PS21050D_APK_MAPPING.md`](PS21050D_APK_MAPPING.md).

## Telepítés HACS-ból

A repository **HACS Custom Repositoryként** adható hozzá:

```text
https://github.com/Mqbretrofit/ha-tmt-chow
```

Típus: **Integration**

Telepítés és Home Assistant újraindítás után:

**Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása → TMT Chow**

A beállítás a Home Assistant felületén történik. Jelentkezz be a TMT Chow fiókoddal, majd válaszd ki a hozzáadni kívánt kaput.

## Fontos

Ez egy közösségi fejlesztés, nem a TMT Automation hivatalos terméke. Kapuautomatizálásnál a fizikai biztonsági eszközöket mindig hagyd megfelelően bekötve, engedélyezve és rendszeresen ellenőrizd őket.