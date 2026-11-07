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
from homeassistant.helpers import config_entry_flow, device_registry as dr
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
    """Stop listening."""
    webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# Removes the Nabu Casa cloudhook too, if the flow made one.
async_remove_entry = config_entry_flow.webhook_async_remove_entry


def bike_key(message: dict[str, Any]) -> str:
    """The app's id for the bike; older app versions only sent its name."""
    return str(message.get("bike_id") or slugify(str(message.get("bike") or "bike")))


def _receive(hass: HomeAssistant, entry: RideBuddyConfigEntry, message: dict[str, Any]) -> None:
    data = entry.runtime_data
    bike_id = bike_key(message)
    known = bike_id in data.bikes
    # Readings the app doesn't have yet are left out of a message; keep the last ones.
    merged = {k: v for k, v in data.bikes.get(bike_id, {}).items() if k not in LATEST_ONLY}
    merged.update({k: v for k, v in message.items() if v is not None})
    data.bikes[bike_id] = merged
    data.store.async_delay_save(lambda: {"bikes": data.bikes}, 5)

    if known:
        _rename_device(hass, entry, bike_id, merged.get("bike"))
        async_dispatcher_send(hass, signal_update(entry.entry_id, bike_id), message)
    else:
        async_dispatcher_send(hass, signal_new_bike(entry.entry_id), bike_id, message)

    hass.bus.async_fire(BUS_EVENT, {"bike_id": bike_id, **message})


def _rename_device(hass: HomeAssistant, entry: RideBuddyConfigEntry, bike_id: str, name: str | None) -> None:
    """The bike was renamed in the app (unless it's been renamed in Home Assistant)."""
    if not name:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (DOMAIN, bike_id) in device.identifiers and device.name != name and not device.name_by_user:
            registry.async_update_device(device.id, name=name)
