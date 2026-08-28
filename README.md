# TMT Chow for Home Assistant

Unofficial Home Assistant custom integration for TMT Automation / TMT Chow (ChowHUB) gate controllers.

## Features

- Gate open / close / stop control through Home Assistant
- Live gate state and position
- Battery sensor
- Read and change supported controller parameters
- Home Assistant config flow setup
- Diagnostics support
- Cloud push / MQTT runtime connection
- 23 interface translations

## Supported languages

Bulgarian, Croatian, Czech, Danish, Dutch, English, Finnish, French, German, Greek, Hungarian, Italian, Norwegian Bokmål, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Spanish, Swedish, Turkish and Ukrainian.

## Installation

### HACS custom repository

1. Open HACS in Home Assistant.
2. Add `https://github.com/Mqbretrofit/ha-tmt-chow` as a custom repository of type **Integration**.
3. Install **TMT Chow**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → TMT Chow**.
6. Sign in with your TMT Chow account and select the gate you want to add.

### Manual installation

Copy `custom_components/tmt_chow` into your Home Assistant `/config/custom_components/` directory and restart Home Assistant.

## Configuration

Setup is performed entirely from the Home Assistant UI. The account password is used only during setup and is not stored by the integration.

## Disclaimer

This is an independent community project and is not an official TMT Automation product. Use gate automation responsibly and keep all physical safety devices enabled and correctly configured.

---

# Magyar

Nem hivatalos Home Assistant integráció TMT Automation / TMT Chow (ChowHUB) kapuvezérlőkhöz.

### Fő funkciók

- Kapu nyitása / zárása / megállítása Home Assistantból
- Élő kapuállapot és pozíció
- Akkumulátor szenzor
- A támogatott vezérlőparaméterek kiolvasása és módosítása
- Grafikus telepítés a Home Assistant felületéről
- Diagnosztika
- 23 nyelv támogatása

A telepítés után: **Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása → TMT Chow**.
