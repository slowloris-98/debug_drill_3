"""Public API views.

Every endpoint here is scoped to the organization that owns the credential on
the request. No response may ever contain another organization's data.
"""

from django.db.models import Count, Sum
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from api.pagination import UsagePagination
from api.serializers import UsageRecordSerializer
from core.models import UsageRecord


def resolve_organization(request):
    """The organization this request is acting as.

    API-key requests carry the key in `request.auth`. The dashboard's own
    fetches are session-authenticated and act as the signed-in user's account.
    """
    if request.auth is not None:
        return request.auth.organization
    return request.user.organization


class UsageRecordListCreateView(generics.ListCreateAPIView):
    """`GET /api/v1/usage/` — the newest-first usage feed for the caller.

    `POST /api/v1/usage/` — ingest one event.
    """

    serializer_class = UsageRecordSerializer
    pagination_class = UsagePagination

    def get_queryset(self):
        return UsageRecord.objects.filter(organization=resolve_organization(self.request))

    def perform_create(self, serializer):
        serializer.save(organization=resolve_organization(self.request))


@method_decorator(cache_page(60), name="dispatch")
class UsageSummaryView(APIView):
    """`GET /api/v1/summary/` — this month's usage rolled up by metric.

    Cached for a minute: the dashboard polls it and the aggregate is expensive.
    """

    def get(self, request):
        organization = resolve_organization(request)
        rows = (
            UsageRecord.objects.filter(organization=organization)
            .values("metric")
            .annotate(events=Count("id"), quantity=Sum("quantity"))
            .order_by("metric")
        )
        return Response(
            {
                "organization": organization.name,
                "metrics": list(rows),
                "total_events": sum(row["events"] for row in rows),
            }
        )
