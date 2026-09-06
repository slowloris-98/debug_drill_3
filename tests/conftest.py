"""Shared fixtures.

The whole suite runs against the demo dataset built by `manage.py seed_demo`,
loaded once into the test database. Each test runs in a transaction that is
rolled back afterwards, so tests may write freely without affecting each other.
"""

import datetime as dt

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from core.models import Organization

MARCH_2026 = dt.date(2026, 3, 1)

# Keys as issued to customers. See `core/management/commands/seed_demo.py`.
HELIO_KEY = "mk_live_helio_7f3a91c4e2"
HELIO_REVOKED_KEY = "mk_live_helio_0b52d8aa16"
VANTAGE_KEY = "mk_live_vantage_4c1e77b930"
UNKNOWN_KEY = "mk_live_helio_0000000000"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed_demo", verbosity=0)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def helio(db):
    return Organization.objects.get(slug="helio")


@pytest.fixture
def vantage(db):
    return Organization.objects.get(slug="vantage")


def auth(key):
    """Header kwargs for an API-key request."""
    return {"HTTP_AUTHORIZATION": f"Api-Key {key}"}
