"""Metered usage rolled up for a billing period.

This is the query finance runs to check a bill against the raw events, and the
one we show a customer when they ask "what did you actually charge us for?"

Rules it is supposed to implement:

  * A billing period runs from its first day to its last day **inclusive**.
    March 2026 means every event from 2026-03-01 00:00:00 up to and including
    2026-03-31 23:59:59.
  * Usage recorded outside the period is never counted in it. An event on
    1 April belongs to April, however close to midnight it landed.
  * The rollup counts the same events the usage feed serves. If the feed and
    the rollup disagree, one of them is wrong.

Written against the tables directly rather than the ORM: finance reads this
query, and it needs to stay something they can read.
"""

from django.db import connection

ROLLUP_SQL = """
    SELECT o.name                            AS organization,
           u.metric                          AS metric,
           COUNT(*)                          AS events,
           SUM(u.quantity)                   AS quantity,
           SUM(u.quantity * u.unit_cost_cents) AS amount_cents
      FROM core_usagerecord u
      JOIN core_organization o ON o.id = u.organization_id
     WHERE DATE(u.recorded_at) BETWEEN %s AND %s
     GROUP BY o.name, u.metric
     ORDER BY o.name, u.metric
"""


def usage_rollup(period_start, period_end):
    """Per-organization, per-metric usage for the billing period."""
    with connection.cursor() as cursor:
        cursor.execute(ROLLUP_SQL, [period_start, period_end])
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def usage_rollup_for(organization_name, period_start, period_end):
    """The same rollup, narrowed to one customer."""
    return [
        row
        for row in usage_rollup(period_start, period_end)
        if row["organization"] == organization_name
    ]


def period_totals(period_start, period_end):
    """Event count and billable amount across every organization."""
    rows = usage_rollup(period_start, period_end)
    return {
        "events": sum(row["events"] for row in rows),
        "amount_cents": sum(row["amount_cents"] for row in rows),
    }
