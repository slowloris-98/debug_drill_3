"""Meterly domain models.

Meterly meters usage for dev-tools SaaS customers. Customer systems push usage
events over the public API; at the end of each month those events are rolled up
into an invoice, credits are applied, and the net is billed.
"""

from django.contrib.auth.models import User
from django.db import models


class Organization(models.Model):
    """A paying customer account. Every other row in the system hangs off one."""

    PLANS = [("starter", "Starter"), ("growth", "Growth"), ("enterprise", "Enterprise")]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    plan = models.CharField(max_length=20, choices=PLANS, default="growth")
    # The account's primary contact. They can sign in to the dashboard.
    owner = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="organization"
    )
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ApiKey(models.Model):
    """Credential for the public API. Sent as `Authorization: Api-Key <key>`.

    Keys are long-lived. Customers rotate them by minting a new key, moving
    their integration over, and revoking the old one. A revoked key must stop
    working immediately and must be rejected in a way the caller can act on.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_keys"
    )
    key = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=80)
    created_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["organization__name", "created_at"]

    @property
    def is_active(self):
        return self.revoked_at is None

    def __str__(self):
        return f"{self.organization.name} / {self.label}"


class UsageRecord(models.Model):
    """One metered event.

    Customers ingest these continuously — there is no quiet period. The public
    feed is served newest-first, and customers page through it nightly to
    reconcile our numbers against their own.
    """

    METRICS = [
        ("api_calls", "API calls"),
        ("build_minutes", "Build minutes"),
        ("seats", "Seats"),
        ("storage_gb", "Storage GB"),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_records"
    )
    metric = models.CharField(max_length=20, choices=METRICS)
    quantity = models.IntegerField()
    unit_cost_cents = models.IntegerField()
    recorded_at = models.DateTimeField(db_index=True)
    # The customer's own identifier for the event. This is what they reconcile against.
    external_id = models.CharField(max_length=64)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.external_id} ({self.metric})"


class Invoice(models.Model):
    """A monthly bill. `net_cents` is what the customer actually owes."""

    STATUSES = [("draft", "Draft"), ("issued", "Issued"), ("paid", "Paid")]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoices"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    gross_cents = models.IntegerField()
    # Credits applied to this invoice. NULL when no credit was issued for the
    # period — the billing importer has always written NULL rather than 0.
    credit_cents = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="issued")
    issued_at = models.DateTimeField()

    class Meta:
        ordering = ["-period_start", "organization__name"]
        unique_together = [("organization", "period_start")]

    def __str__(self):
        return f"{self.organization.name} {self.period_start}"


class WebhookEndpoint(models.Model):
    """Where we notify a customer about overages."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    url = models.URLField()
    secret = models.CharField(max_length=64)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.url


class WebhookDelivery(models.Model):
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_type = models.CharField(max_length=40)
    status_code = models.IntegerField(null=True, blank=True)
    attempts = models.IntegerField(default=1)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]
