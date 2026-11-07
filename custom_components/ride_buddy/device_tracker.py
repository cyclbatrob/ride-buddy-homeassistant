"""Ride Buddy device tracker: where the bike's parked, when the app includes the location.

Only made for a bike once a message has had a location in it ("Include the bike's location"
in the app), so it doesn't sit there unknown for riders who keep it off.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RideBuddyConfigEntry
from .const import signal_new_bike, signal_update
from .entity import RideBuddyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: RideBuddyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    tracked: set[str] = set()

    @callback
    def maybe_add(bike_id: str, message: dict[str, Any] | None = None) -> None:
        bike = entry.runtime_data.bikes.get(bike_id, {})
        if bike_id in tracked or bike.get("lat") is None or bike.get("lon") is None:
            return
        tracked.add(bike_id)
        async_add_entities([RideBuddyTracker(entry, bike_id)])

    for bike_id in entry.runtime_data.bikes:
        maybe_add(bike_id)
        # A bike that starts sending its location later.
        entry.async_on_unload(
            async_dispatcher_connect(hass, signal_update(entry.entry_id, bike_id), callback(lambda m, b=bike_id: maybe_add(b, m)))
        )

    @callback
    def new_bike(bike_id: str, message: dict[str, Any]) -> None:
        maybe_add(bike_id, message)
        entry.async_on_unload(
            async_dispatcher_connect(hass, signal_update(entry.entry_id, bike_id), callback(lambda m, b=bike_id: maybe_add(b, m)))
        )

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_bike(entry.entry_id), new_bike))


class RideBuddyTracker(RideBuddyEntity, TrackerEntity):
    """Where a bike was last parked."""

    _attr_name = None  # the device's name: device_tracker.tiger_900_rally_pro

    def __init__(self, entry: RideBuddyConfigEntry, bike_id: str) -> None:
        super().__init__(entry, bike_id, "location")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.bike.get("lat")

    @property
    def longitude(self) -> float | None:
        return self.bike.get("lon")

    @property
    def location_accuracy(self) -> float:
        return float(self.bike.get("accuracy_m") or 0)
