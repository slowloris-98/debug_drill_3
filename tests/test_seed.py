"""Environment gate.

If these three fail, the dataset is wrong and nothing else in the suite means
anything. Fix that before you start the clock.
"""

import pytest

from core.models import Invoice, Organization, UsageRecord
from tests.conftest import MARCH_2026

pytestmark = pytest.mark.django_db


def test_the_dataset_has_eleven_customer_organizations():
    assert Organization.objects.count() == 11


def test_helio_ingested_4812_events_in_march():
    count = UsageRecord.objects.filter(organization__slug="helio").count()
    assert count == 4812, f"expected Helio's signed-off March event count, got {count}"


def test_four_march_invoices_carry_no_credit():
    no_credit = Invoice.objects.filter(period_start=MARCH_2026, credit_cents__isnull=True)
    assert no_credit.count() == 4, (
        "four March invoices had no credit issued: "
        f"{sorted(no_credit.values_list('organization__name', flat=True))}"
    )
