"""Shared base for Ride Buddy entities: one device per bike, updated by the webhook."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from . import RideBuddyConfigEntry
from .const import DOMAIN, signal_update


class RideBuddyEntity(Entity):
    """An entity of one bike."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: RideBuddyConfigEntry, bike_id: str, key: str) -> None:
        self._entry = entry
        self._bike_id = bike_id
        self._attr_unique_id = f"{bike_id}_{key}"
        self._attr_translation_key = key
        bike = self.bike
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, bike_id)},
            name=bike.get("bike") or "Bike",
            manufacturer="Ride Buddy",
            model=bike.get("model"),
        )

    @property
    def bike(self) -> dict[str, Any]:
        """Everything the bike has sent, latest values first."""
        return self._entry.runtime_data.bikes.get(self._bike_id, {})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._entry.entry_id, self._bike_id), self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: dict[str, Any]) -> None:
        self.async_write_ha_state()
