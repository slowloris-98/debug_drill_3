"""Walking the public usage feed.

Customers reconcile nightly: they walk `/api/v1/usage/` from the first page to
the last and compare our event count against their own. Their ingestion does
not pause while they walk it, and ours does not either.

The contract: a full walk returns every record exactly once — no record on two
pages, no record skipped — even though the feed is being written to.
"""

import pytest
from django.utils import timezone

from core.models import UsageRecord
from tests.conftest import HELIO_KEY, auth

pytestmark = pytest.mark.django_db

USAGE = "/api/v1/usage/"


def _ids(payload):
    return [row["id"] for row in payload["results"]]


def _walk(api_client, url=USAGE, max_pages=250):
    """Follow `next` to the end, collecting ids in order."""
    collected = []
    pages = 0
    while url and pages < max_pages:
        payload = api_client.get(url, **auth(HELIO_KEY)).json()
        collected.extend(_ids(payload))
        url = payload["next"]
        pages += 1
    return collected


def test_ingestion_during_a_walk_does_not_repeat_a_record(api_client, helio):
    first = api_client.get(USAGE, **auth(HELIO_KEY)).json()
    page_one = _ids(first)

    # Helio's pipeline keeps pushing while their reconciliation job pages.
    UsageRecord.objects.create(
        organization=helio,
        metric="api_calls",
        quantity=17,
        unit_cost_cents=2,
        recorded_at=timezone.now(),
        external_id="evt_helio_live_00001",
    )

    page_two = _ids(api_client.get(first["next"], **auth(HELIO_KEY)).json())

    repeated = sorted(set(page_one) & set(page_two))
    assert not repeated, f"{len(repeated)} record(s) served on both pages: {repeated}"


def test_a_full_walk_of_a_quiet_feed_returns_every_record_exactly_once(api_client):
    collected = _walk(api_client)
    total = UsageRecord.objects.filter(organization__slug="helio").count()
    assert len(collected) == len(set(collected)), (
        f"{len(collected) - len(set(collected))} duplicate(s) across the walk"
    )
    assert len(set(collected)) == total, f"walked {len(set(collected))} of {total} records"


def test_the_feed_is_served_newest_first(api_client):
    rows = api_client.get(USAGE, **auth(HELIO_KEY)).json()["results"]
    stamps = [row["recorded_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)
