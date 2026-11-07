"""Ride Buddy: the bike's details from the Ride Buddy iPhone app, pushed to a webhook.

The app posts JSON when the bike's parked, when it's arriving home, after a fill-up and when
something needs doing. Each bike becomes a device (keyed by the app's `bike_id`) with sensors,
binary sensors, an event entity and, if the app includes the location, a device tracker. The
latest values are stored, so entities keep them across restarts until the next message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_flow, device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import BUS_EVENT, DOMAIN, LATEST_ONLY, signal_new_bike, signal_update

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.EVENT]
STORAGE_VERSION = 1


@dataclass
class RideBuddyData:
    """What each bike last sent, by bike id."""

    store: Store
    bikes: dict[str, dict[str, Any]] = field(default_factory=dict)


type RideBuddyConfigEntry = ConfigEntry[RideBuddyData]


async def async_setup_entry(hass: HomeAssistant, entry: RideBuddyConfigEntry) -> bool:
    """Start listening on the entry's webhook."""
    store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    saved = await store.async_load() or {}
    entry.runtime_data = RideBuddyData(store=store, bikes=saved.get("bikes", {}))

    async def handle_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        try:
            message = await request.json()
        except ValueError:
            return web.Response(status=400, text="Expected JSON")
        if not isinstance(message, dict):
            return web.Response(status=400, text="Expected a JSON object")
        _receive(hass, entry, message)
        return web.Response(text="OK")

    webhook.async_register(
        hass, DOMAIN, "Ride Buddy", entry.data[CONF_WEBHOOK_ID], handle_webhook, allowed_methods=["POST"]
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RideBuddyConfigEntry) -> bool:
    """Stop listening, and save now: a reload reads the store straight back."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    await entry.runtime_data.store.async_save({"bikes": entry.runtime_data.bikes})
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# Removes the Nabu Casa cloudhook too, if the flow made one.
async_remove_entry = config_entry_flow.webhook_async_remove_entry


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: RideBuddyConfigEntry, device: dr.DeviceEntry
) -> bool:
    """A bike's device can be deleted (⋮ → Delete). It comes back if the bike sends again."""
    data = entry.runtime_data
    for domain, key in device.identifiers:
        if domain == DOMAIN:
            data.bikes.pop(key, None)
    data.store.async_delay_save(lambda: {"bikes": data.bikes}, 1)
    return True


def bike_key(message: dict[str, Any]) -> str:
    """The app's id for the bike; older app versions only sent its name."""
    return str(message.get("bike_id") or slugify(str(message.get("bike") or "bike")))


def _receive(hass: HomeAssistant, entry: RideBuddyConfigEntry, message: dict[str, Any]) -> None:
    data = entry.runtime_data
    bike_id = bike_key(message)
    # Known by its name (an app from before bike_id): one device now, under its id.
    adopted = bool(message.get("bike_id")) and _adopt_named(hass, entry, bike_id, message.get("bike"))
    known = bike_id in data.bikes
    # Readings the app doesn't have yet are left out of a message; keep the last ones.
    merged = {k: v for k, v in data.bikes.get(bike_id, {}).items() if k not in LATEST_ONLY}
    merged.update({k: v for k, v in message.items() if v is not None})
    data.bikes[bike_id] = merged
    data.store.async_delay_save(lambda: {"bikes": data.bikes}, 5)

    if adopted:
        # The entities are rebuilt with the new keys (the reload starts straight away, so only
        # once this message is in).
        hass.config_entries.async_schedule_reload(entry.entry_id)
    elif known:
        _rename_device(hass, entry, bike_id, merged.get("bike"))
        async_dispatcher_send(hass, signal_update(entry.entry_id, bike_id), message)
    else:
        async_dispatcher_send(hass, signal_new_bike(entry.entry_id), bike_id, message)

    hass.bus.async_fire(BUS_EVENT, {"bike_id": bike_id, **message})


def _adopt_named(hass: HomeAssistant, entry: RideBuddyConfigEntry, bike_id: str, name: str | None) -> bool:
    """Moves a bike known by its name onto its id, keeping the older device (its area and
    entity ids, which automations may use). If the id has its own device already (both apps
    sent), that one's entities go and its area moves over. True if anything moved."""
    data = entry.runtime_data
    old_key = slugify(str(name or ""))
    if not old_key or old_key == bike_id or old_key not in data.bikes or data.bikes[old_key].get("bike_id"):
        return False
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    def device(key: str) -> dr.DeviceEntry | None:
        return next((d for d in dr.async_entries_for_config_entry(devices, entry.entry_id)
                     if (DOMAIN, key) in d.identifiers), None)

    old_device, new_device = device(old_key), device(bike_id)
    area = None
    if new_device:
        area = new_device.area_id
        for entity in er.async_entries_for_device(entities, new_device.id, include_disabled_entities=True):
            entities.async_remove(entity.entity_id)
        devices.async_remove_device(new_device.id)
    if old_device:
        devices.async_update_device(
            old_device.id, new_identifiers={(DOMAIN, bike_id)}, area_id=old_device.area_id or area
        )
        for entity in er.async_entries_for_config_entry(entities, entry.entry_id):
            if entity.unique_id.startswith(f"{old_key}_"):
                entities.async_update_entity(
                    entity.entity_id, new_unique_id=bike_id + entity.unique_id[len(old_key):]
                )
    data.bikes[bike_id] = data.bikes.pop(old_key) | data.bikes.get(bike_id, {})
    return True


def _rename_device(hass: HomeAssistant, entry: RideBuddyConfigEntry, bike_id: str, name: str | None) -> None:
    """The bike was renamed in the app (unless it's been renamed in Home Assistant)."""
    if not name:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (DOMAIN, bike_id) in device.identifiers and device.name != name and not device.name_by_user:
            registry.async_update_device(device.id, name=name)
