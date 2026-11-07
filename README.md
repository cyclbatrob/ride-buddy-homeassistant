# Ride Buddy for Home Assistant

[![hassfest](https://github.com/cyclbatrob/ride-buddy-homeassistant/actions/workflows/hassfest.yml/badge.svg)](https://github.com/cyclbatrob/ride-buddy-homeassistant/actions/workflows/hassfest.yml)
[![HACS](https://github.com/cyclbatrob/ride-buddy-homeassistant/actions/workflows/hacs.yml/badge.svg)](https://github.com/cyclbatrob/ride-buddy-homeassistant/actions/workflows/hacs.yml)

The Home Assistant side of **Ride Buddy**, an iPhone app for motorcycles that records rides and
reads the bike's data (odometer, fuel, tyre pressures...) through an OBD adapter.

The app sends each bike's details to Home Assistant when it's parked (at home or anywhere
else), when you're arriving home, after a fill-up, and when something needs doing (a reminder,
a tyre or battery warning, a fault code). The **Ride Buddy integration** turns that into a
device per bike, with its sensors, so there's nothing to write in YAML.

## 1. Install the integration

**With HACS:** HACS → ⋮ → Custom repositories → add
`https://github.com/cyclbatrob/ride-buddy-homeassistant` as an **Integration** → install
**Ride Buddy** → restart Home Assistant.

**By hand:** copy `custom_components/ride_buddy/` from this repo into your Home Assistant
config folder's `custom_components/` (so you have `config/custom_components/ride_buddy/__init__.py`)
and restart.

Then Settings → Devices & services → **Add integration** → **Ride Buddy** → Submit. It shows a
**webhook URL**: copy it.

- With **Home Assistant Cloud** (Nabu Casa) the URL is a cloud one, which the phone can reach
  from anywhere.
- Otherwise it's your instance's own address (the external one if you've set it, else the
  internal one). An internal address only works when the phone's on the home wifi.
- Lost it? The integration's ⋮ → **Reconfigure** shows it again. It doesn't change.

## 2. Ride Buddy side

Settings → Connections → Home Assistant:

- **Webhook URL**: paste it, then **Send test**. It should say "Test received", and the bike
  appears under the integration as a device.
- **Home location**: tap "Use where it's parked" while the bike is parked at home. It stays on
  the phone; it decides between "parked at home" and "parked".
- **Include the bike's location**: on, and the bike gets a device tracker (where it's parked).
- iOS asks for **Local Network** access the first time you use a local address: allow it.

If the phone isn't on the home wifi yet when the bike's switched off, iOS sends it as soon as it
can (it's a background upload).

## What you get

One device per bike (named as in the app, renamed when you rename it there), with:

| Entity | What |
|---|---|
| `sensor.<bike>_odometer` | The odometer (miles if the app uses miles) |
| `sensor.<bike>_fuel`, `_fuel_left` | Tank level (%) and litres left |
| `sensor.<bike>_range` | Range at the recent economy |
| `sensor.<bike>_front_tyre`, `_rear_tyre` | Tyre pressures (psi) |
| `sensor.<bike>_battery` | Battery voltage |
| `sensor.<bike>_service_due_in` | Distance to the next service |
| `sensor.<bike>_fault_codes` | How many fault codes are stored |
| `sensor.<bike>_needs_doing` | The most urgent thing on the Garage page, or "Nothing due" |
| `sensor.<bike>_last_ride_distance`, `_last_ride_time` | The last ride |
| `binary_sensor.<bike>_chain_lube_due`, `_fault_codes`, `_needs_attention` | Problems, on when there's something to do |
| `event.<bike>_bike_event` | What just happened: parked at home, parked, arriving home, fill-up, something needs doing, test |
| `device_tracker.<bike>` | Where it's parked (only with "Include the bike's location" on) |

Readings the app doesn't have (tyre pressures before they're decoded, say) are left out of a
message, and the last value is kept. Everything survives a Home Assistant restart.

A bike you no longer have can be deleted from its device page (⋮ → Delete); it comes back if
the app sends it again. A bike that an older app version sent by name only is joined onto its
device the first time the current app sends it, keeping that device's entity ids and area.

Every message is also fired on the event bus as `ride_buddy_event`, with the whole message as
its data (plus `bike_id`).

## Example automations

Lights on when arriving home after dark (in the UI: When → Entity → Event, pick the bike's
event entity and "Arriving home"):

```yaml
automation:
  - alias: Bike arriving home
    triggers:
      - trigger: state
        entity_id: event.tiger_900_rally_pro_bike_event
        attribute: event_type
        to: arriving_home
    conditions:
      - condition: sun
        after: sunset
    actions:
      - action: light.turn_on
        target:
          entity_id: light.garage
```

A nudge when something needs doing:

```yaml
  - alias: Bike needs attention
    triggers:
      - trigger: state
        entity_id: event.tiger_900_rally_pro_bike_event
        attribute: event_type
        to: alert
    actions:
      - action: notify.notify
        data:
          title: Tiger
          message: "{{ state_attr('event.tiger_900_rally_pro_bike_event', 'new_alerts') | join(', ') }}"
```

(A state trigger on `event_type` with `to:` doesn't fire when the same event comes twice in a
row. To catch every one, trigger on the event entity's state with no `to:`, and check
`trigger.to_state.attributes.event_type` in a condition.)

## Moving from the old YAML set-up

Before the integration, the Ride Buddy docs had a block of trigger-based template sensors (`Tiger
odometer`, `Tiger last event`…) on a webhook you made up. To move over:

1. Add the integration as above and paste its URL into the app. The app carries on sending
   the same fields, so the old sensors would keep working, but they won't get anything now.
2. Delete the `template:` block with `webhook_id: ride_buddy_…` from your configuration, and
   reload template entities (or restart).
3. Point automations at the new entities (`sensor.tiger_last_event` → the event entity).

## What gets sent

```json
{
  "version": 2,
  "event": "parked_home",
  "time": "2026-11-07T15:58:00Z",
  "bike": "Tiger 900 Rally Pro",
  "bike_id": "3F2A6C1E-9B47-4D2B-8E5A-0C7D1F4B9A21",
  "units": "miles",
  "odometer_km": 5646, "odometer_mi": 3508,
  "fuel_pct": 75, "fuel_l": 12.3,
  "range_km": 251, "range_mi": 156,
  "tyre_front_psi": 34.2, "tyre_rear_psi": 38.5,
  "battery_v": 12.61,
  "fault_codes": 0,
  "chain_lube_due": true,
  "service_due_km": 13666, "service_due_mi": 8492,
  "last_ride": { "km": 162.2, "mi": 100.8, "min": 318 },
  "top_alert": "Rear tyre losing pressure"
}
```

Events: `parked_home`, `parked` (switched off away from home), `arriving_home` (within 500 m of
home on a ride), `fill_up` (adds `fuel_before_pct` and `fuel_after_pct`), `alert` (adds
`new_alerts`, a list of headlines) and `test`. With the location on: `lat`, `lon` and
`accuracy_m`. The `_mi` fields are for the old YAML sensors.

## Developing

The tests run the integration inside a real Home Assistant with its test kit (Python 3.13 or
later):

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m pytest
```

## Licence

MIT. Not affiliated with any motorcycle maker.
