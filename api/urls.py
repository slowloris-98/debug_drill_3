from django.urls import path

from api import views

urlpatterns = [
    path("usage/", views.UsageRecordListCreateView.as_view(), name="usage-list"),
    path("summary/", views.UsageSummaryView.as_view(), name="usage-summary"),
]
