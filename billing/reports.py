"""Monthly billing reports.

Rules these functions are supposed to implement:

  * An invoice's **net** is its gross minus any credit applied to it.
  * An invoice with no credit nets its full gross. "No credit" and "a zero
    credit" mean the same thing to a customer.
  * Every issued invoice for the period appears in the summary, and the
    summary's rows must add up to the reported revenue total.
"""

from django.db.models import F, Sum

from core.models import Invoice


def invoice_summary(period_start):
    """One row per issued invoice for the period, largest first."""
    return list(
        Invoice.objects.filter(period_start=period_start)
        .annotate(net_cents=F("gross_cents") - F("credit_cents"))
        .order_by("-gross_cents")
        .values("organization__name", "gross_cents", "credit_cents", "net_cents")
    )


def revenue_total(period_start):
    """Total net revenue owed to us for the period, in cents."""
    return (
        Invoice.objects.filter(period_start=period_start)
        .annotate(net_cents=F("gross_cents") - F("credit_cents"))
        .aggregate(total=Sum("net_cents"))["total"]
        or 0
    )
