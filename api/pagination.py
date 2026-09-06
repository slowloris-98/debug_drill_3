"""Pagination for the public usage feed.

The feed is served newest-first and customers walk it end to end every night to
reconcile our event count against theirs. Ingestion does not stop while they
walk it.
"""

from rest_framework.pagination import PageNumberPagination


class UsagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
