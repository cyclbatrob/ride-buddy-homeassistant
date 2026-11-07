"""The Ride Buddy integration: setup flow, webhook messages, entities and restarts."""

import json
from pathlib import Path
import re

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.ride_buddy import async_remove_config_entry_device
from custom_components.ride_buddy.const import DOMAIN

TIGER = {
    "event": "parked_home",
    "time": "2026-11-07T15:58:00Z",
    "bike": "Tiger 900 Rally Pro",
    "bike_id": "3F2A6C1E-9B47-4D2B-8E5A-0C7D1F4B9A21",
    "units": "miles",
    "odometer_km": 5645.6, "odometer_mi": 3508,
    "fuel_pct": 75, "fuel_l": 12.3,
    "range_km": 251.0, "range_mi": 156,
    "tyre_front_psi": 34.2, "tyre_rear_psi": 38.5,
    "battery_v": 12.61,
    "fault_codes": 0,
    "chain_lube_due": True,
    "service_due_km": 13666.0,
    "last_ride": {"km": 162.2, "mi": 100.8, "min": 318},
    "top_alert": "Rear tyre losing pressure",
}


async def _add(hass: HomeAssistant):
    await async_setup_component(hass, "homeassistant", {})
    await async_setup_component(hass, "webhook", {})
    hass.config.external_url = "https://bikes.example.com"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    webhook_id = result["result"].data["webhook_id"]
    assert result["description_placeholders"]["webhook_url"] == f"https://bikes.example.com/api/webhook/{webhook_id}"
    await hass.async_block_till_done()
    return result["result"], webhook_id


async def _post(hass, client, webhook_id, body):
    response = await client.post(f"/api/webhook/{webhook_id}", json=body)
    assert response.status == 200
    await hass.async_block_till_done()


def _entity(hass, platform, key):
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{TIGER['bike_id']}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_bike_appears_with_its_readings(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    await _post(hass, client, webhook_id, TIGER)

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [d.name for d in devices] == ["Tiger 900 Rally Pro"]

    odometer = _entity(hass, "sensor", "odometer")
    assert odometer.entity_id == "sensor.tiger_900_rally_pro_odometer"
    assert odometer.attributes["friendly_name"] == "Tiger 900 Rally Pro Odometer"
    assert _entity(hass, "event", "event").entity_id == "event.tiger_900_rally_pro_bike_event"
    assert odometer.attributes["unit_of_measurement"] == "mi"
    assert round(float(odometer.state)) == 3508
    assert round(float(_entity(hass, "sensor", "range").state)) == 156
    assert _entity(hass, "sensor", "tyre_rear").state == "38.5"
    assert _entity(hass, "sensor", "fuel_left").state == "12.3"
    assert _entity(hass, "sensor", "top_alert").state == "Rear tyre losing pressure"
    assert _entity(hass, "binary_sensor", "chain_lube_due").state == "on"
    assert _entity(hass, "binary_sensor", "fault_codes_present").state == "off"
    event = _entity(hass, "event", "event")
    assert event.attributes["event_type"] == "parked_home"
    assert event.attributes["top_alert"] == "Rear tyre losing pressure"
    # No location sent: no tracker.
    assert er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, f"{TIGER['bike_id']}_location") is None


async def test_later_messages_keep_readings_and_clear_alerts(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    await _post(hass, client, webhook_id, TIGER)
    later = {k: v for k, v in TIGER.items() if k not in ("tyre_rear_psi", "top_alert")}
    later |= {"event": "fill_up", "fuel_pct": 100, "fuel_before_pct": 50, "fuel_after_pct": 100, "lat": 53.2590, "lon": -1.9110}
    await _post(hass, client, webhook_id, later)

    assert _entity(hass, "sensor", "tyre_rear").state == "38.5"  # not in the message: kept
    assert _entity(hass, "sensor", "fuel").state == "100"
    assert _entity(hass, "sensor", "top_alert").state == "Nothing due"
    assert _entity(hass, "binary_sensor", "needs_attention").state == "off"
    event = _entity(hass, "event", "event")
    assert event.attributes["event_type"] == "fill_up" and event.attributes["fuel_before_pct"] == 50
    tracker = _entity(hass, "device_tracker", "location")
    assert tracker.attributes["latitude"] == 53.2590


async def test_readings_survive_a_restart(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    await _post(hass, client, webhook_id, TIGER)
    await entry.runtime_data.store.async_save({"bikes": entry.runtime_data.bikes})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _entity(hass, "sensor", "tyre_front").state == "34.2"
    # The event entity keeps the last event across a restart (Home Assistant restores it).
    assert _entity(hass, "event", "event").attributes["event_type"] == "parked_home"


async def test_older_app_message_without_bike_id(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    old = {"event": "test", "bike": "Tiger 900", "odometer_mi": 3506, "odometer_km": 5642, "range_mi": 233, "fault_codes": 0}
    await _post(hass, client, webhook_id, old)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "tiger_900_range")
    assert round(float(hass.states.get(entity_id).state)) == 233


async def test_each_bike_is_its_own_device(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The app sends one message per bike (Send test sends them all)."""
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    vfr = {"version": 2, "event": "test", "bike": "VFR800", "bike_id": "6B1D0E52-1C4E-4F7A-9D83-5E2A7C0F9B14",
           "units": "miles", "fault_codes": 0, "chain_lube_due": False, "last_ride": {"km": 1.4, "mi": 0.9, "min": 3}}
    norton = vfr | {"bike": "Norton Atlas", "bike_id": "C0A9E7F3-2B58-4D16-8E4C-71F3A2D9B605", "last_ride": {"km": 40.0, "min": 55}}
    for message in (TIGER, vfr, norton):
        await _post(hass, client, webhook_id, message)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert sorted(d.name for d in devices) == ["Norton Atlas", "Tiger 900 Rally Pro", "VFR800"]
    distance = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{norton['bike_id']}_last_ride_distance")
    assert round(float(hass.states.get(distance).state), 1) == round(40.0 / 1.609344, 1)


async def test_bike_known_by_name_joins_its_id(hass: HomeAssistant, hass_client_no_auth) -> None:
    """An app from before bike_id made a device keyed by the bike's name; the new app's message
    makes it one device, keeping the old entity ids and the area."""
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    old = {"event": "test", "bike": TIGER["bike"], "odometer_mi": 3500, "odometer_km": 5632.7, "tyre_front_psi": 33.0}
    await _post(hass, client, webhook_id, old)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    old_device = dr.async_entries_for_config_entry(devices, entry.entry_id)[0]
    area = ar.async_get(hass).async_create("Motorcycles")
    devices.async_update_device(old_device.id, area_id=area.id)
    old_odometer = entities.async_get_entity_id("sensor", DOMAIN, "tiger_900_rally_pro_odometer")

    # Both apps sent: a second device for the same bike, keyed by its id.
    await _post(hass, client, webhook_id, {k: v for k, v in TIGER.items() if k != "tyre_front_psi"})
    await hass.async_block_till_done()

    remaining = dr.async_entries_for_config_entry(devices, entry.entry_id)
    assert len(remaining) == 1
    assert remaining[0].identifiers == {(DOMAIN, TIGER["bike_id"])} and remaining[0].area_id == area.id
    odometer = _entity(hass, "sensor", "odometer")
    assert odometer.entity_id == old_odometer == "sensor.tiger_900_rally_pro_odometer"
    assert round(float(odometer.state)) == 3508
    assert _entity(hass, "sensor", "tyre_front").state == "33.0"  # only the old app had sent it
    assert set(entry.runtime_data.bikes) == {TIGER["bike_id"]}


async def test_a_bike_can_be_deleted(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    await _post(hass, client, webhook_id, TIGER)
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    assert await async_remove_config_entry_device(hass, entry, device)
    assert entry.runtime_data.bikes == {}


async def test_bad_message_is_refused(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry, webhook_id = await _add(hass)
    client = await hass_client_no_auth()
    response = await client.post(f"/api/webhook/{webhook_id}", data="not json")
    assert response.status == 400


async def test_every_screen_gets_its_placeholders(hass: HomeAssistant) -> None:
    """A {placeholder} with no value shows as a translation error in the dialog (and hassfest
    refuses web addresses in the text, so they can only come in as placeholders)."""
    strings = json.loads((Path(__file__).parents[1] / "custom_components/ride_buddy/strings.json").read_text())
    def needed(text):
        return set(re.findall(r"{(\w+)}", text))

    await async_setup_component(hass, "homeassistant", {})
    await async_setup_component(hass, "webhook", {})
    for text in [strings["config"]["step"]["user"]["description"], strings["config"]["create_entry"]["default"]]:
        assert "http" not in text
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert needed(strings["config"]["step"]["user"]["description"]) <= set(result.get("description_placeholders") or {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert needed(strings["config"]["create_entry"]["default"]) <= set(result["description_placeholders"])


async def test_reconfigure_shows_the_url_again(hass: HomeAssistant) -> None:
    entry, webhook_id = await _add(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["description_placeholders"]["webhook_url"].endswith(webhook_id)
