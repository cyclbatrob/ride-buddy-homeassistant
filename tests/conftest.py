"""Run with Home Assistant's test kit (pytest-homeassistant-custom-component), from the repo root:
    pytest
"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
