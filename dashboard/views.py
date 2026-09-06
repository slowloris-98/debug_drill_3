import datetime as dt

from django.shortcuts import render

from billing.reports import invoice_summary, revenue_total

MARCH_2026 = dt.date(2026, 3, 1)


def money(cents):
    """Render a cent amount for display. An absent amount stays absent."""
    if cents is None:
        return None
    return f"${cents / 100:,.2f}"


def invoice_report(request):
    """Finance's month-end view. Marcus Bell reads this every morning."""
    period_start = MARCH_2026
    rows = [
        {
            "name": row["organization__name"],
            "gross": money(row["gross_cents"]),
            "credit": money(row["credit_cents"]),
            "net": money(row["net_cents"]),
        }
        for row in invoice_summary(period_start)
    ]
    return render(
        request,
        "dashboard/invoices.html",
        {
            "period_start": period_start,
            "rows": rows,
            "total": money(revenue_total(period_start)),
            "row_count": len(rows),
        },
    )
