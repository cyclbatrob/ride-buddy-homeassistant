"""Adding Ride Buddy: makes a webhook and shows its address to paste into the app.

With Nabu Casa it's a cloudhook, so the phone can reach it from anywhere; otherwise it's the
instance's own address (external if set, else internal).
"""

from homeassistant.helpers import config_entry_flow

from .const import DOCS_URL, DOMAIN

config_entry_flow.register_webhook_flow(DOMAIN, "Ride Buddy", {"docs_url": DOCS_URL})
