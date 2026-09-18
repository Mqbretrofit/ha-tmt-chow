# TMT Chow for Home Assistant

[![Release](https://img.shields.io/badge/release-v1.0.4--beta.34-orange)](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.34)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://www.hacs.xyz/)
[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Mqbretrofit&repository=ha-tmt-chow&category=integration)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-EA4AAA?logo=githubsponsors)](https://github.com/sponsors/Mqbretrofit)

Unofficial Home Assistant custom integration for **TMT Automation / TMT Chow (ChowHUB)** gate controllers.

The integration brings supported TMT Chow gates into Home Assistant as native entities, allowing gate control, pedestrian / partial opening, live status monitoring, controller configuration and automation from the Home Assistant UI.

## ❤️ Support development

TMT Chow for Home Assistant is an independent open-source community project. Continued development includes protocol research, controller mapping, diagnostics, regression testing and real-hardware validation.

If this integration is useful to you, you can support continued development through **[GitHub Sponsors](https://github.com/sponsors/Mqbretrofit)**. For sponsored feature requests, priority development and additional support options, see **[SUPPORT.md](SUPPORT.md)**.

> **Current release:** [`v1.0.4-beta.34`](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.34) (pre-release)
>
> Last non-beta release: `v1.0.3`

## What's new in v1.0.4-beta.34

- Fixes PS25142 issue #51: valid native `ACK RP,1` replies are now unwrapped from the OURANOS JSON envelope before decoding.
- The confirmed 18-value Proposal-B frame is now decoded into the PS25142 parameter entities instead of leaving all 18 unavailable.
- Diagnostics now inspect the real UART `DATA` frame, report the correct 18-token count, and expose the decoded values.
- Regression tests include the exact real-hardware response `ACK RP,1:1,8,0,3,0,1,5,0,0,0,0,2,3,0,0,0,1,1`.
- PS25142 cover status/control and all previously verified controller routes remain unchanged.

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
- Power saving mode on PS25142

Parameter availability, order and wire encoding are selected from the detected controller model. Parameter changes are written back to the controller and then read again so Home Assistant only reflects the controller's confirmed state.

`PS21053` / `PS21053C` parameter handling has been validated on real hardware. `PED OPEN` has also been verified on a real `PS21053C` controller with `ACK PED OPEN` and partial-position feedback.

For `PS21050D`, a real installation has verified the account/live identity pair (`PS21050` account model, `PS21050D` live `DEV INFO`), the 20-value parameter frame, Home Assistant parameter entities and the corrected open/closed state handling. TMT Chow 3.1.4 contains the `PS21050` product implementation and no separate `PS21050D` implementation, so the integration uses the vendor PS21050 definitions only for this exact verified alias. The PS21050D write format and option tables are APK-derived and protected by mandatory read-before-write and read-back verification.

The remaining mapped controller models are implemented from the vendor TMT Chow 3.1.4 and gatePRO Smart! 1.0.0 APK/XAPK definitions and should be considered APK-derived until independently validated on matching hardware. Unknown/API-only controller models are not assigned guessed parameter schemas or optional capabilities.

For the complete PS21050D vendor mapping and protocol notes, see [`PS21050D_APK_MAPPING.md`](PS21050D_APK_MAPPING.md).

## Hardware-tested controllers

The table deliberately separates real-hardware evidence from APK/proposal-derived support. “Verified” applies only to the functions listed in that row; it does not mean that every optional command or every possible parameter value has been exercised.

| Account model | Live controller / hardware | Real-hardware evidence | Current status |
| --- | --- | --- | --- |
| `PS21053` | `PS21053` / `PS21053C` | Gate control and status, 17-slot parameter read/write with app-visible persistence, guarded full-frame readback, and `PED OPEN` with ACK and partial-position feedback | Verified for the listed functions |
| `PS21050` | `PS21050D` | Exact account/live identity, 20-slot parameter frame and entities, live state handling; write codec and option tables are APK-derived and protected by read-before-write/full readback | Hardware-tested, with APK-derived parameter mapping |
| `PS21050` | `PS21050C` | Exact account/live identity, 20-slot live frame, parameter entities and pedestrian capability observed in real diagnostics; writes use the guarded PS21050 full-frame transaction | Hardware-observed; not every write/value independently exercised |
| `PS22027` | `PS22027` | 20-slot frame, Hall-current decoding and a full read → one write → readback transaction; Alarm Buzzer persisted and matched the official app | Verified for the tested write; risky mode/current transitions remain guarded |
| `PS22087` | `PS22087B` / `P710U` | 15-slot `F1..F9,A..F` frame and an `F8` value change with the other 14 fields preserved; undocumented `B` and `D` stay read-only | Verified for the tested write and full-frame preservation |
| `PS19001` | `PS19001`, 20-character UID | Native IOTC/RDT status/control path and the corrected 19-slot `1..J` UART0 parameter frame used by the current profile | Verified on the documented native profile; x86-64 and local six-digit PIN required |
| `PS25007` | `PS25007A` / `P500BU` | Exact identity and 17-slot parameter profile; pedestrian behavior has controller-specific safety history | Parameters supported; `PED OPEN` remains an explicitly guarded test path, not a generally verified safe capability |
| `PS25142` | `PS25142`, 20-character UID | OURANOS/IOTC-RDT transport and UART V3.0 live state; `FULL OPEN`, `FULL CLOSE` and `STOP` all returned ACK and physically worked; Home Assistant followed `Opening → Open → Closing → Closed` correctly on real hardware | ✅ **Verified working:** normal cover status, position, open, close and stop. All 18 Proposal-B parameters are exposed; the guarded RP,1/WP,1 write path is implemented, but an actual parameter change has not yet been independently exercised on this hardware |

The other mapped controller classes remain APK/proposal-derived until matching hardware confirms their exact runtime identity, status route, optional controls and parameter layout. **PS25142 is now confirmed working on real hardware in Home Assistant for live status, position, open, close and stop.** Its exact 18-slot parameter definition comes from the controller's tested Proposal B profile and uses the APK-derived UART V3.0 AutoProduct RP,1/WP,1 transport with strict full-frame verification.

## Unknown or unsupported controller: what to do

Starting with `v1.0.4-beta.34`, one Home Assistant diagnostics download performs the safe discovery work needed for an unknown or unverified controller. It checks the classic AWS IoT Shadow, cloud Proposal/FunctionSet data and the known read-only WBT request dialects (`RS`, `READ STATUS`, `RP,1`, `READ FUNCTION`), then records which of those dialects returned ACK, NAK or no usable reply. For vendor `uuid_type=1` devices it can also test the native OURANOS `READ STATUS` and `RS` routes when the local six-digit gate PIN is configured.

1. Install the latest test release and restart Home Assistant.
2. Add the gate normally with the TMT Chow integration. Do not assign another controller's parameter profile manually.
3. If the diagnostics identify `uuid_type=1`, open **Settings → Devices & services → TMT Chow → Configure**, save the gate's six-digit PIN, then restart/reload the integration. The PIN is stored locally and redacted from diagnostics.
4. Open the TMT Chow integration entry, choose **Download diagnostics**, and wait for the read-only probes to finish. One download is enough; do not install a chain of controller-specific probe builds.
5. Open a [new GitHub issue](https://github.com/Mqbretrofit/ha-tmt-chow/issues/new) and attach the diagnostics JSON. Also include the exact account model, the model printed on the controller/board, the live model shown by the official app if available, the TMT Chow app version, and which functions work in the official app.
6. Do not post passwords, the six-digit PIN, certificates, private keys or unredacted cloud credentials. Review the file before uploading even though the integration redacts known secrets.
7. Do not test raw movement, relay, learning, reset or parameter-write commands unless a maintainer provides a controller-specific, safety-reviewed procedure. The automatic diagnostic never sends those commands.

The useful sections in the downloaded JSON are `controller_route_analysis`, `unknown_controller_read_matrix`, `ouranos_read_matrix`, `proposal_summary`, the configured/live controller identity and the sanitized observed payloads. They show which transport answered, which read command worked, where the data came from and what evidence is still missing.

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

`v1.0.4-beta.21` automatically removes the four unavailable PS19001 parameter entities left in Home Assistant's entity registry by the obsolete 23-slot beta profile. The cleanup is restricted to `parameter_20` through `parameter_23` of the same PS19001 config entry; the 19 working parameters and all other controllers remain unchanged.

`v1.0.4-beta.20` corrects PS19001 parameter support to the real-hardware-confirmed 19-value UART0 frame (`1` through `J`). The four extra APK entries are current-mapping helpers, not wire parameters. Parameter changes use a fresh full read, one write with no automatic retry, and a mandatory exact full-frame readback. The already proven PS19001 movement and status paths are unchanged.

`v1.0.4-beta.19` adds explicit `PS21050C` support for accounts configured as `PS21050`, including the APK-derived pedestrian control and the real-hardware-confirmed 20-value parameter frame. Parameter changes use a fresh full read, one write with no automatic retry, and a mandatory exact full-frame readback.

### PS19001 native control

`v1.0.4-beta.17` added native control for the confirmed PS19001 / 20-character UID case: full open, full close, stop, pedestrian opening and live status. Beta.20 corrected the parameter profile to the real 19-slot `1..J` UART0 frame. Existing AWS/MQTT controllers continue to use their unchanged cloud-push and command paths.

The native reader currently supports x86-64 Home Assistant installations. On its first run it downloads pinned TUTK IOTC/RDT 3.1.5.38 libraries and a private glibc runtime, verifies their cryptographic hashes, then caches the required files under Home Assistant's `.storage` directory. The TUTK pair is from the same 3.1.5 API generation as the 3.1.5.33 libraries embedded in the TMT Chow Android application.

To enable automatic status:

1. Open **Settings → Devices & services → TMT Chow**.
2. Open **Configure** for the PS19001 gate.
3. Enter the gate's six-digit TMT Chow PIN and save.

The PIN is stored locally in the Home Assistant config entry, displayed as a password field, passed to the isolated helper over standard input, and redacted from diagnostics. Clear the field and save to disable native operation. The helper keeps one IOTC/RDT connection alive and accepts only a fixed allowlist of PS19001 operations; arbitrary wire commands are rejected. Parameter changes use a fresh full read, one complete write with no automatic retry, and a mandatory readback verification. Successful status reads are scheduled 15 seconds apart and failed attempts back off to 60 seconds. A valid last-known native state keeps the cover available for up to 15 minutes, and the **Refresh native gate status** button reuses the persistent connection for an immediate read. The original one-shot `tmt_chow.ouranos_probe` diagnostic action remains unchanged.

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

Current release: **[v1.0.4-beta.34](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.34)** (pre-release)

Last non-beta release: **v1.0.3**

## Disclaimer

This is an **independent community project** and is not an official TMT Automation product.

A gate is a moving physical system. Use automations responsibly and keep all required photocells, safety inputs, obstacle detection and other physical safety devices enabled, correctly installed and tested.

---

# Magyar

Nem hivatalos Home Assistant integráció **TMT Automation / TMT Chow (ChowHUB)** kapuvezérlőkhöz.

## ❤️ A fejlesztés támogatása

A TMT Chow for Home Assistant egy független, nyílt forráskódú közösségi projekt. A folyamatos fejlesztés része a protokollkutatás, a vezérlők feltérképezése, a diagnosztika, a regressziós tesztelés és a valódi hardveres ellenőrzés.

Ha hasznos számodra az integráció, a fejlesztést a **[GitHub Sponsors](https://github.com/sponsors/Mqbretrofit)** oldalon támogathatod. Támogatott funkciókéréshez, kiemelt fejlesztéshez és további lehetőségekhez lásd a **[SUPPORT.md](SUPPORT.md)** fájlt.

> **Jelenlegi kiadás:** [`v1.0.4-beta.34`](https://github.com/Mqbretrofit/ha-tmt-chow/releases/tag/v1.0.4-beta.34) (előzetes kiadás)
>
> Utolsó nem beta kiadás: `v1.0.3`

## Újdonságok a v1.0.4-beta.34-ben

- Javítja a PS25142 #51 hibát: a natív `ACK RP,1` választ az integráció már először kibontja az OURANOS JSON burkolatból, és csak utána dekódolja.
- A valódi hardveren kapott 18 értékes Proposal-B keret most már betöltődik a PS25142 paraméter-entitásokba, így nem marad mind a 18 „Unavailable”.
- A diagnosztika a valódi UART `DATA` keretet vizsgálja, helyesen 18 tokent jelez, és megmutatja a dekódolt értékeket is.
- Regressziós teszt került be a pontos hardveres válaszra: `ACK RP,1:1,8,0,3,0,1,5,0,0,0,0,2,3,0,0,0,1,1`.
- A PS25142 cover állapot/vezérlés és minden korábban igazolt vezérlőútvonal változatlan.

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

Az integráció a TMT Chow 3.1.4/3.2.0 és a gatePRO Smart! 1.0.0 APK/XAPK vezérlődefiníciói alapján modellenként kezeli a kapuvezérlők képességeit, paraméterlistáját és UART paraméterprotokollját. A támogatási katalógus 217 konkrét kapuvezérlő-modellhez tartalmaz paramétersémát és protokollprofilt.

A `PS21053` / `PS21053C` paraméterkezelése valódi hardveren validálva lett. A `PED OPEN` parancs `PS21053C` vezérlőn szintén valódi hardveren ellenőrzött: `ACK PED OPEN` válasszal és részleges pozíció-visszajelzéssel.

A `PS21050D` esetén valódi telepítésen igazolt a `PS21050` fiókmodell / `PS21050D` élő `DEV INFO` páros, a 20 értékes paraméterkeret, a Home Assistant paraméter-entitások és a javított nyitott/zárt állapotkezelés. A TMT Chow 3.1.4 APK-ban külön PS21050D implementáció nincs; az integráció ezért csak ennél a pontosan igazolt alias-párnál használja a gyári PS21050 definíciókat. A paraméterírás formátuma és opciótáblái APK-ból származnak, az írást pedig kötelező előolvasás és visszaellenőrzés védi.

A többi leképezett modell támogatása az APK/XAPK gyári definícióiból származik, ezért az adott hardveren történő külön validálásig APK-alapú támogatásnak tekintendő. Ismeretlen vagy csak API-ból látott vezérlőhöz az integráció nem rendel találgatással paramétersémát vagy opcionális vezérlési képességet.

A teljes PS21050D paraméter- és protokolltérkép: [`PS21050D_APK_MAPPING.md`](PS21050D_APK_MAPPING.md).

## Valós hardveren tesztelt vezérlők

A táblázat szándékosan különválasztja a valódi hardveres bizonyítékot az APK-/proposal-alapú támogatástól. Az „igazolt” csak az adott sorban felsorolt funkciókra vonatkozik; nem jelenti azt, hogy minden opcionális parancsot és minden lehetséges paraméterértéket kipróbáltunk.

| Fiókmodell | Élő vezérlő / hardver | Valós hardveres bizonyíték | Jelenlegi állapot |
| --- | --- | --- | --- |
| `PS21053` | `PS21053` / `PS21053C` | Kapuvezérlés és állapot, 17 mezős paraméterolvasás/-írás az appban is megmaradó módosítással, teljes visszaellenőrzés, valamint `PED OPEN` ACK-kal és részleges pozíció-visszajelzéssel | A felsorolt funkciók igazoltak |
| `PS21050` | `PS21050D` | Pontos fiók-/élőmodell-pár, 20 mezős paraméterkeret és entitások, élő állapotkezelés; az írási codec és az opciótáblák APK-ból származnak, előolvasás és teljes visszaellenőrzés védi őket | Hardveren tesztelt, APK-alapú paramétertérképpel |
| `PS21050` | `PS21050C` | Pontos fiók-/élőmodell-pár, 20 mezős élő keret, paraméter-entitások és gyalogos képesség valós diagnosztikában; az írás a védett PS21050 teljeskeretes tranzakciót használja | Hardveren megfigyelt; nem minden írás/érték lett külön kipróbálva |
| `PS22027` | `PS22027` | 20 mezős keret, Hall-áram dekódolása és teljes olvasás → egyetlen írás → visszaolvasás; az Alarm Buzzer módosítása megmaradt és a hivatalos appban is egyezett | A tesztelt írás igazolt; a kockázatos mód-/áramváltások továbbra is védettek |
| `PS22087` | `PS22087B` / `P710U` | 15 mezős `F1..F9,A..F` keret és egy `F8` módosítás a másik 14 mező változatlan megőrzésével; a dokumentálatlan `B` és `D` csak olvasható | A tesztelt írás és a teljes keret megőrzése igazolt |
| `PS19001` | `PS19001`, 20 karakteres UID | Natív IOTC/RDT állapot-/vezérlési útvonal és a jelenlegi profil javított, 19 mezős `1..J` UART0 paraméterkerete | A dokumentált natív profil igazolt; x86-64 rendszer és helyben tárolt hatjegyű PIN szükséges |
| `PS25007` | `PS25007A` / `P500BU` | Pontos azonosítás és 17 mezős paraméterprofil; a gyalogos működéshez vezérlőspecifikus biztonsági előzmény tartozik | Paraméterek támogatva; a `PED OPEN` külön védett tesztútvonal, nem általánosan igazolt biztonságos képesség |
| `PS25142` | `PS25142`, 20 karakteres UID | OURANOS/IOTC-RDT transport és UART V3.0 élő állapot; a `FULL OPEN`, `FULL CLOSE` és `STOP` mind ACK-ot adott és fizikailag helyesen működött; a Home Assistant valós hardveren helyesen követte a `Nyitás → Nyitva → Zárás → Zárva` állapotot | ✅ **Igazoltan működik:** normál cover állapot, pozíció, nyitás, zárás és STOP. Mind a 18 Proposal-B paraméter megjelenik; a védett RP,1/WP,1 írási útvonal elkészült, de konkrét paramétermódosítás ezen a hardveren még nem lett külön kipróbálva |

A többi leképezett vezérlőosztály azonos hardveren végzett ellenőrzésig APK-/proposal-alapú. **A PS25142 Home Assistant támogatása valós hardveren igazoltan működik az élő állapot, pozíció, nyitás, zárás és STOP funkciókkal.** A pontos 18 mezős paraméterdefiníció a vezérlő tesztelt Proposal B profiljából jön, az UART V3.0 AutoProduct `RP,1`/`WP,1` transportot pedig teljes előolvasás és teljeskeretes visszaellenőrzés védi.

## Ismeretlen vagy nem támogatott vezérlő: mit tegyen a felhasználó?

A `v1.0.4-beta.34` verziótól egyetlen Home Assistant-diagnosztika elvégzi az ismeretlen vagy még nem igazolt vezérlő biztonságos felderítését. Ellenőrzi a klasszikus AWS IoT Shadow útvonalat, a felhős Proposal/FunctionSet adatokat és az ismert, csak olvasási WBT-kéréseket (`RS`, `READ STATUS`, `RP,1`, `READ FUNCTION`), majd feljegyzi, melyik vonal adott ACK-t, NAK-ot vagy használható választ. A gyártó által `uuid_type=1` értékkel jelölt eszközöknél a natív OURANOS `READ STATUS` és `RS` útvonalat is megpróbálja, ha a helyi hatjegyű kapu-PIN be van állítva.

1. Telepítsd a legújabb tesztverziót, majd indítsd újra a Home Assistantot.
2. Add hozzá a kaput normál módon a TMT Chow integrációval. Ne rendeld hozzá kézzel egy másik vezérlő paraméterprofilját.
3. Ha a diagnosztika `uuid_type=1` értéket jelez, nyisd meg a **Beállítások → Eszközök és szolgáltatások → TMT Chow → Beállítás** menüt, add meg a kapu hatjegyű PIN-kódját, majd töltsd újra az integrációt. A PIN helyben marad, és a diagnosztikában maszkolva van.
4. A TMT Chow integráció bejegyzésénél válaszd a **Diagnosztika letöltése** lehetőséget, és várd meg a csak olvasási próbák végét. Egyetlen letöltés elegendő; nem kell egymás után több vezérlőspecifikus próbaverziót telepíteni.
5. Nyiss egy [új GitHub issue-t](https://github.com/Mqbretrofit/ha-tmt-chow/issues/new), és csatold a diagnosztikai JSON-t. Írd mellé a pontos fiókmodellt, a vezérlőn/panelen olvasható típust, a hivatalos appban látható élő modellt, a TMT Chow app verzióját és azt, hogy mely funkciók működnek a hivatalos appban.
6. Ne tölts fel jelszót, hatjegyű PIN-t, tanúsítványt, privát kulcsot vagy maszkolatlan felhős hitelesítő adatot. Feltöltés előtt nézd át a fájlt akkor is, ha az integráció az ismert titkokat automatikusan kitakarja.
7. Nyers mozgási, relé-, tanítási, reset- vagy paraméterírási parancsot csak vezérlőspecifikus, biztonságilag átnézett karbantartói eljárással tesztelj. Az automatikus diagnosztika ilyen parancsot soha nem küld.

A letöltött JSON legfontosabb részei: `controller_route_analysis`, `unknown_controller_read_matrix`, `ouranos_read_matrix`, `proposal_summary`, a beállított/élő vezérlőazonosító és a maszkolt megfigyelt payloadok. Ezekből látszik, melyik transport válaszolt, melyik olvasási kérés működött, honnan érkezett az adat, és milyen bizonyíték hiányzik még.

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
