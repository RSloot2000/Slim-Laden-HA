# Peblar Slim Laden — Home Assistant custom integration

Deze repo is gemaakt voor persoonlijk gebruik en zal zeer waarschijnlijk niet werken met andere setups.

Zet de bestaande "Peblar slim laden"-automatisering (regellus + accu-leren +
observability + TimescaleDB-pijplijn) om naar één custom integration met config
flow, een coordinator als regellus en eigen instel-entiteiten.

## Installatie

1. Kopieer de map `custom_components/peblar_slim_laden/` naar `/config/custom_components/`
   op je HA-instance (VM `192.168.1.227`, map `/config`).
2. Herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen** en zoek
   **Peblar Slim Laden**.
4. Koppel in de config flow de entiteiten:
   - Lader status: `sensor.peblar_ev_charger_status`
   - Laadvermogen: `sensor.peblar_ev_charger_vermogen`
   - Sessie-energie: `sensor.peblar_ev_charger_sessie_energie`
   - Waarschuwingen: `binary_sensor.peblar_ev_charger_waarschuwingen`
   - Fouten: `binary_sensor.peblar_ev_charger_fouten`
   - Auto SoC: `sensor.jdx_43_b_state_of_charge`
   - Netvermogen (P1): `sensor.p1_meter_vermogen`
   - PV huidig vermogen: `sensor.hoymiles_dtu_41211001149813_current_power`
   - Laden aan/uit: `switch.peblar_ev_charger_opladen`
   - Dwing enkelvoudige fase: `switch.peblar_ev_charger_dwing_enkelvoudige_fase_af`
   - Laadlimiet: `number.peblar_ev_charger_laadlimiet`
   - Herstart-knop: `button.peblar_ev_charger_herstarten`
   - (optioneel) Voorklimatisering: `switch.jdx_43_b_voorverwarming_klimaatregeling`
   - (optioneel) PV opbrengst vandaag: `sensor.hoymiles_dtu_41211001149813_daily_energy`
   - (optioneel) Solcast: `_resterende_voorspelling_vandaag`, `_voorspelling_morgen`,
     `_huidig_vermogen`, `_voorspelling_vandaag` (detailedForecast)
   - (optioneel) TimescaleDB URL: `postgresql://ha:***@192.168.1.251:5452/homeassistant`

## Veilig overzetten (observe-only)

De schakelaar **Regelen actief** staat standaard **uit**. Zolang die uit is
berekent de integratie alles en publiceert het de observability-sensoren en
(indien geconfigureerd) de TimescaleDB-logging, maar stuurt hij de lader **niet**
aan. Zo kun je de integratie een paar cycli naast de bestaande automatisering
laten draaien en de `sensor.peblar_slim_laden_*`-waarden vergelijken.

Zodra je vertrouwen hebt:

1. Schakel de oude automations uit: *"Peblar slim laden (...)"*,
   *"Peblar slim laden – instellingen gewijzigd"* en
   *"Peblar accu-capaciteit leren (sessie-zuiver)"*.
2. Verwijder/stop de pyscript-app `peblar_learn` (de integratie neemt de
   observability + DB-pijplijn over).
3. Zet **Regelen actief** aan.

## Wat de integratie levert

- **Instellingen** (entiteiten): laadmodus, doel-SoC, accu-capaciteit (geleerd),
  PV-marge, min/max A, zon-benutfactor, fasewissel-interval, vertrektijd/-datum,
  dagelijkse vertrektijd, slim laden aan, laadlimiet-override, andere auto aan
  lader, debug-meldingen, en **regelen actief** (observe-only gate).
- **Observability**: `sensor.peblar_slim_laden_*` (SoC, target, vloer, ramp,
  urgentie, W/A, zon, fases, DB-status, ...).
- **Regellus**: elke 2 minuten + gedebounced op bronwijzigingen.
- **Leren**: accu-capaciteit per sessie (EMA) + W/A-EMA, persistent opgeslagen.
- **TimescaleDB**: cyclus-logging, sessiedetectie (elke 10 min) en
  forecast-accuraatheid (00:10 voorspelling, 23:55 werkelijk). Het schema
  (`peb_charge_cycle`, `peb_charge_session`, `peb_forecast_accuracy`) moet al
  bestaan; Node-RED-tabellen worden niet aangeraakt.

## Preclimate

Zolang de voorklimatisering-switch aan staat blijft de lader laden — ook bij een
volle accu — en levert hij minimaal ~3500 W, zodat de klimaatlast uit het net/de
lader komt i.p.v. uit de auto-accu. De auto begrenst dit zelf; W/A-leren en
accu-capaciteit-leren worden tijdens preclimate onderdrukt.

## Tests

`python tests/test_calc.py` draait een pariteits-/smoke-test van de rekenlogica
zonder Home Assistant.
