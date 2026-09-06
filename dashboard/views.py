import datetime as dt

from django.shortcuts import render

from billing.reports import invoice_summary, revenue_total

MARCH_2026 = dt.date(2026, 3, 1)


def invoice_report(request):
    """Finance's month-end view. Marcus Bell reads this every morning."""
    period_start = MARCH_2026
    rows = invoice_summary(period_start)
    return render(
        request,
        "dashboard/invoices.html",
        {
            "period_start": period_start,
            "rows": rows,
            "total_cents": revenue_total(period_start),
            "row_count": len(rows),
        },
    )
