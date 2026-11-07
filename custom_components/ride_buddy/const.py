"""Constants for Ride Buddy."""

DOMAIN = "ride_buddy"
DOCS_URL = "https://github.com/cyclbatrob/ride-buddy-homeassistant"

# What the app sends in "event".
EVENT_TYPES = ["parked_home", "parked", "arriving_home", "fill_up", "alert", "test"]

# Fired on the event bus for every message, for YAML automations.
BUS_EVENT = f"{DOMAIN}_event"

# Keys that describe "now" rather than a reading: taken from the latest message only, so an
# alert that's been dealt with goes away instead of sticking.
LATEST_ONLY = ("event", "time", "top_alert", "new_alerts", "fuel_before_pct", "fuel_after_pct", "awake")


def signal_new_bike(entry_id: str) -> str:
    """Dispatcher signal: a bike Home Assistant hasn't seen before sent something."""
    return f"{DOMAIN}_{entry_id}_new_bike"


def signal_update(entry_id: str, bike_id: str) -> str:
    """Dispatcher signal: a bike sent something."""
    return f"{DOMAIN}_{entry_id}_{bike_id}_update"
