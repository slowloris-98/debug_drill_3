"""March 2026 close.

Finance has signed off on these figures (see the ground-truth block at the top
of `core/management/commands/seed_demo.py`):

    gross    5,890,100 cents
    credits    233,750 cents
    NET      5,656,350 cents   =  $56,563.50
"""

import pytest

from billing.reports import invoice_summary, revenue_total
from tests.conftest import MARCH_2026

pytestmark = pytest.mark.django_db

MARCH_NET_CENTS = 5_656_350


def _row(rows, name):
    return next(row for row in rows if row["organization__name"] == name)


def test_march_net_revenue_matches_the_signed_off_figure():
    total = revenue_total(MARCH_2026)
    assert total == MARCH_NET_CENTS, (
        f"reported ${total / 100:,.2f}, finance signed off ${MARCH_NET_CENTS / 100:,.2f}"
    )


def test_every_invoice_reports_a_net_amount():
    rows = invoice_summary(MARCH_2026)
    blank = [row["organization__name"] for row in rows if row["net_cents"] is None]
    assert not blank, f"invoices with no net amount: {blank}"


def test_an_invoice_with_no_credit_nets_its_full_gross():
    # Vantage Freight was issued no credit in March, so they owe all of it.
    row = _row(invoice_summary(MARCH_2026), "Vantage Freight")
    assert row["net_cents"] == 968_500


def test_an_invoice_with_a_credit_still_has_it_subtracted():
    # Helio Robotics: 1,482,000 gross less a 120,000 credit.
    row = _row(invoice_summary(MARCH_2026), "Helio Robotics")
    assert row["net_cents"] == 1_362_000


def test_all_eleven_invoices_appear_in_the_summary():
    assert len(invoice_summary(MARCH_2026)) == 11


def test_the_summary_rows_add_up_to_the_reported_total():
    rows = invoice_summary(MARCH_2026)
    assert sum(row["net_cents"] or 0 for row in rows) == revenue_total(MARCH_2026)
