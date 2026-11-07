"""Ride Buddy event entity: what just happened (parked at home, arriving home, fill-up, alert).

For automations: trigger on the entity's state changing, with `event_type` in the attributes,
or pick it in the UI's "Entity → Event" trigger.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RideBuddyConfigEntry
from .const import EVENT_TYPES, signal_new_bike
from .entity import RideBuddyEntity

# What goes along with each event, besides the readings (which are on the sensors).
EVENT_EXTRAS = ("new_alerts", "top_alert", "fuel_before_pct", "fuel_after_pct")


async def async_setup_entry(
    hass: HomeAssistant, entry: RideBuddyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for bike_id in entry.runtime_data.bikes:
        async_add_entities([RideBuddyEvent(entry, bike_id)])

    @callback
    def new_bike(bike_id: str, message: dict[str, Any]) -> None:
        entity = RideBuddyEvent(entry, bike_id, first=message)
        async_add_entities([entity])

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_bike(entry.entry_id), new_bike))


class RideBuddyEvent(RideBuddyEntity, EventEntity):
    """The bike's latest event."""

    _attr_event_types = EVENT_TYPES

    def __init__(self, entry: RideBuddyConfigEntry, bike_id: str, first: dict[str, Any] | None = None) -> None:
        super().__init__(entry, bike_id, "event")
        # The message that introduced the bike arrives before the entity exists.
        self._first = first

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._first is not None:
            self._handle_message(self._first)
            self._first = None

    @callback
    def _handle_message(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event not in EVENT_TYPES:
            return
        self._trigger_event(event, {k: message[k] for k in EVENT_EXTRAS if message.get(k) is not None})
        self.async_write_ha_state()
