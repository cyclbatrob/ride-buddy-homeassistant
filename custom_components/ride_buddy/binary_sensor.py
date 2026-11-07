"""Ride Buddy binary sensors: things that need doing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RideBuddyConfigEntry
from .const import signal_new_bike
from .entity import RideBuddyEntity


@dataclass(frozen=True, kw_only=True)
class RideBuddyBinaryDescription(BinarySensorEntityDescription):
    """A yes/no and how to read it from the app's message."""

    value: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[RideBuddyBinaryDescription, ...] = (
    RideBuddyBinaryDescription(
        key="chain_lube_due",
        value=lambda bike: bike.get("chain_lube_due"),
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    RideBuddyBinaryDescription(
        key="fault_codes_present",
        value=lambda bike: None if bike.get("fault_codes") is None else bike["fault_codes"] > 0,
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    RideBuddyBinaryDescription(
        key="needs_attention",
        value=lambda bike: bool(bike.get("top_alert")),
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: RideBuddyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def add(bike_id: str) -> None:
        async_add_entities(RideBuddyBinarySensor(entry, bike_id, description) for description in BINARY_SENSORS)

    for bike_id in entry.runtime_data.bikes:
        add(bike_id)

    @callback
    def new_bike(bike_id: str, message: dict[str, Any]) -> None:
        add(bike_id)

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_bike(entry.entry_id), new_bike))


class RideBuddyBinarySensor(RideBuddyEntity, BinarySensorEntity):
    """A yes/no about a bike."""

    entity_description: RideBuddyBinaryDescription

    def __init__(self, entry: RideBuddyConfigEntry, bike_id: str, description: RideBuddyBinaryDescription) -> None:
        super().__init__(entry, bike_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.bike)
