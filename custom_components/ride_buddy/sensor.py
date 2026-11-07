"""Ride Buddy sensors: odometer, fuel, range, tyres, battery, service, last ride."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import RideBuddyConfigEntry
from .const import signal_new_bike
from .entity import RideBuddyEntity


@dataclass(frozen=True, kw_only=True)
class RideBuddySensorDescription(SensorEntityDescription):
    """A sensor and where its value is in the app's message."""

    value: Callable[[dict[str, Any]], Any]
    # Shown in miles for a rider who uses miles in the app (only applies when it's first added).
    miles: bool = False


def _number(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda bike: bike.get(key)


def _km(km_key: str, mi_key: str) -> Callable[[dict[str, Any]], Any]:
    """Older app versions only sent some distances in miles."""
    def value(bike: dict[str, Any]) -> Any:
        if (km := bike.get(km_key)) is not None:
            return km
        if (mi := bike.get(mi_key)) is not None:
            return round(mi * 1.609344, 1)
        return None

    return value


def _last_ride(key: str) -> Callable[[dict[str, Any]], Any]:
    def value(bike: dict[str, Any]) -> Any:
        ride = bike.get("last_ride") or {}
        if key == "km":
            return ride.get("km") if ride.get("km") is not None else (round(ride["mi"] * 1.609344, 1) if "mi" in ride else None)
        return ride.get(key)

    return value


def _time(bike: dict[str, Any]) -> datetime | None:
    return dt_util.parse_datetime(bike["time"]) if bike.get("time") else None


SENSORS: tuple[RideBuddySensorDescription, ...] = (
    RideBuddySensorDescription(
        key="odometer",
        value=_number("odometer_km"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        miles=True,
    ),
    RideBuddySensorDescription(
        key="fuel",
        value=_number("fuel_pct"),
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    RideBuddySensorDescription(
        key="fuel_left",
        value=_number("fuel_l"),
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    RideBuddySensorDescription(
        key="range",
        value=_km("range_km", "range_mi"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        miles=True,
    ),
    RideBuddySensorDescription(
        key="tyre_front",
        # Tyre pressures stay in psi; a metric Home Assistant would show kPa otherwise.
        value=_number("tyre_front_psi"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    RideBuddySensorDescription(
        key="tyre_rear",
        value=_number("tyre_rear_psi"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    RideBuddySensorDescription(
        key="battery",
        value=_number("battery_v"),
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    RideBuddySensorDescription(
        key="service_due",
        value=_km("service_due_km", "service_due_mi"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        miles=True,
    ),
    RideBuddySensorDescription(
        key="fault_codes",
        value=_number("fault_codes"),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RideBuddySensorDescription(
        key="top_alert",
        value=lambda bike: bike.get("top_alert") or "Nothing due",
    ),
    RideBuddySensorDescription(
        key="last_ride_distance",
        value=_last_ride("km"),
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        miles=True,
    ),
    RideBuddySensorDescription(
        key="last_ride_duration",
        value=_last_ride("min"),
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
    ),
    RideBuddySensorDescription(
        key="last_update",
        value=_time,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: RideBuddyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def add(bike_id: str) -> None:
        async_add_entities(RideBuddySensor(entry, bike_id, description) for description in SENSORS)

    for bike_id in entry.runtime_data.bikes:
        add(bike_id)

    @callback
    def new_bike(bike_id: str, message: dict[str, Any]) -> None:
        add(bike_id)

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_bike(entry.entry_id), new_bike))


class RideBuddySensor(RideBuddyEntity, SensorEntity):
    """One reading of a bike."""

    entity_description: RideBuddySensorDescription

    def __init__(self, entry: RideBuddyConfigEntry, bike_id: str, description: RideBuddySensorDescription) -> None:
        super().__init__(entry, bike_id, description.key)
        self.entity_description = description
        if description.miles and self.bike.get("units", "miles") == "miles":
            self._attr_suggested_unit_of_measurement = UnitOfLength.MILES

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.bike)
