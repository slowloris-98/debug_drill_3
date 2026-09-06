"""The metered-usage rollup for a billing period.

A billing period runs from its first day to its last day inclusive. March 2026
means every event from 2026-03-01 00:00:00 through 2026-03-31 23:59:59, and
nothing from April.

Seeded truth (see `core/management/commands/seed_demo.py`):

    8,182 events in March, 247 of them on the 31st.
    55 events on 1 April, none later.
    Sundial Media: 155 events on each metric in March, 29,824 build minutes.
"""

import datetime as dt

import pytest

from billing.usage_rollup import period_totals, usage_rollup, usage_rollup_for
from core.models import UsageRecord

pytestmark = pytest.mark.django_db

MARCH_START = dt.date(2026, 3, 1)
MARCH_END = dt.date(2026, 3, 31)
APRIL_START = dt.date(2026, 4, 1)

MARCH_EVENTS = 8_182
SUNDIAL_BUILD_MINUTES = 29_824


def test_the_march_rollup_counts_events_recorded_on_the_last_day():
    counted = period_totals(MARCH_START, MARCH_END)["events"]
    assert counted == MARCH_EVENTS, (
        f"rolled up {counted} events, March holds {MARCH_EVENTS} "
        f"({MARCH_EVENTS - counted} unaccounted for)"
    )


def test_a_customers_march_build_minutes_match_their_own_ci_logs():
    rows = usage_rollup_for("Sundial Media", MARCH_START, MARCH_END)
    build = next(row for row in rows if row["metric"] == "build_minutes")
    assert build["quantity"] == SUNDIAL_BUILD_MINUTES, (
        f"billed {build['quantity']} build minutes, Sundial ran {SUNDIAL_BUILD_MINUTES}"
    )


def test_march_and_april_together_account_for_every_event():
    # No event may fall between two consecutive periods, and none may land in
    # both. March closes on the 31st; April opens on the 1st.
    march = period_totals(MARCH_START, MARCH_END)["events"]
    april = period_totals(APRIL_START, APRIL_START)["events"]
    assert march + april == UsageRecord.objects.count(), (
        f"March {march} + April {april} != {UsageRecord.objects.count()} stored events"
    )


def test_every_organization_appears_in_the_march_rollup():
    names = {row["organization"] for row in usage_rollup(MARCH_START, MARCH_END)}
    assert len(names) == 11
