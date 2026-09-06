"""Rebuild the demo dataset. Safe to run repeatedly: it drops and recreates.

    python manage.py seed_demo

GROUND TRUTH (this is the oracle for the March 2026 books — finance has signed
off on these figures and they are what the reports are supposed to produce):

    Gross billed .............. 5,890,100 cents  ($58,901.00)
    Credits applied ............. 233,750 cents     ($2,337.50)
    NET OWED .................. 5,656,350 cents  ($56,563.50)   <- the number that matters

    11 invoices, one per organization.
    FOUR of them have credit_cents = NULL, not 0: Vantage Freight,
    Pallas Analytics, Northbeam Studios, Ferrous Supply. The billing importer
    has always written NULL when no credit was issued for the period.

    Helio Robotics ingested exactly 4,812 usage events in March. 240 of those
    arrived as a single backfill batch and therefore share one identical
    recorded_at (2026-03-18T02:00:00Z).
"""

import datetime as dt
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    ApiKey,
    Invoice,
    Organization,
    UsageRecord,
    WebhookDelivery,
    WebhookEndpoint,
)

UTC = dt.timezone.utc

# name, slug, plan, owner username, owner full name, gross_cents, credit_cents, usage_count
ACCOUNTS = [
    ("Helio Robotics",    "helio",      "enterprise", "rokafor",   "Rina Okafor",      1_482_000, 120_000, 4812),
    ("Vantage Freight",   "vantage",    "enterprise", "draman",    "Dev Raman",          968_500,    None,  900),
    ("Sundial Media",     "sundial",    "growth",     "jhalloran", "Jo Halloran",        734_200,  45_000,  620),
    ("Pallas Analytics",  "pallas",     "growth",     "amcgrath",  "Aoife McGrath",      610_750,    None,  480),
    ("Corvid Labs",       "corvid",     "growth",     "tnakamura", "Taro Nakamura",      528_400,  28_400,  350),
    ("Northbeam Studios", "northbeam",  "growth",     "lferreira", "Lucia Ferreira",     412_300,    None,  260),
    ("Quillon Data",      "quillon",    "growth",     "sbaptiste", "Serge Baptiste",     355_900,  15_900,  220),
    ("Ferrous Supply",    "ferrous",    "starter",    "hkoenig",   "Hana Koenig",        288_600,    None,  180),
    ("Larkfield Health",  "larkfield",  "starter",    "pvasquez",  "Pilar Vasquez",      214_750,   9_750,  150),
    ("Sable Networks",    "sable",      "starter",    "ochukwu",   "Obi Chukwu",         176_300,   6_300,  120),
    ("Otterbrook Games",  "otterbrook", "starter",    "eberglund", "Elin Berglund",      118_400,   8_400,   90),
]

# Long-lived API keys. Helio rotated theirs on 2026-03-24: they minted
# ...7f3a91c4e2 and revoked the old ...0b52d8aa16 the same afternoon.
API_KEYS = [
    ("helio",      "mk_live_helio_7f3a91c4e2",      "production (rotated 2026-03-24)", None),
    ("helio",      "mk_live_helio_0b52d8aa16",      "production (retired)",            dt.datetime(2026, 3, 24, 16, 40, tzinfo=UTC)),
    ("vantage",    "mk_live_vantage_4c1e77b930",    "production",                      None),
    ("sundial",    "mk_live_sundial_9d20b6f1a5",    "production",                      None),
    ("pallas",     "mk_live_pallas_2a8f45c703",     "production",                      None),
    ("corvid",     "mk_live_corvid_6e93b1d284",     "production",                      None),
    ("northbeam",  "mk_live_northbeam_be4072a95c",  "production",                      None),
    ("quillon",    "mk_live_quillon_31d7ae6b08",    "production",                      None),
]

METRIC_COSTS = [("api_calls", 2), ("build_minutes", 35), ("seats", 4500), ("storage_gb", 18)]

MARCH_START = dt.date(2026, 3, 1)
MARCH_END = dt.date(2026, 3, 31)
ISSUED_AT = dt.datetime(2026, 4, 1, 9, 15, tzinfo=UTC)
BACKFILL_AT = dt.datetime(2026, 3, 18, 2, 0, 0, tzinfo=UTC)


class Command(BaseCommand):
    help = "Drop and rebuild the Meterly demo dataset."

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(20260402)

        WebhookDelivery.objects.all().delete()
        WebhookEndpoint.objects.all().delete()
        UsageRecord.objects.all().delete()
        Invoice.objects.all().delete()
        ApiKey.objects.all().delete()
        Organization.objects.all().delete()
        User.objects.all().delete()

        # Marcus Bell runs finance ops. He is the one reading the dashboard.
        User.objects.create_superuser(
            username="mbell", email="marcus.bell@meterly.io", password="meterly",
            first_name="Marcus", last_name="Bell",
        )

        orgs = {}
        for name, slug, plan, username, full_name, gross, credit, usage_count in ACCOUNTS:
            first, last = full_name.split(" ", 1)
            user = User.objects.create_user(
                username=username, email=f"{username}@{slug}.example",
                password="meterly", first_name=first, last_name=last, is_staff=True,
            )
            org = Organization.objects.create(
                name=name, slug=slug, plan=plan, owner=user,
                created_at=dt.datetime(2024, 6, 1, tzinfo=UTC),
            )
            orgs[slug] = org

            Invoice.objects.create(
                organization=org,
                period_start=MARCH_START,
                period_end=MARCH_END,
                gross_cents=gross,
                credit_cents=credit,
                status="issued",
                issued_at=ISSUED_AT,
            )

            self._seed_usage(org, usage_count, rng)

        for slug, key, label, revoked_at in API_KEYS:
            ApiKey.objects.create(
                organization=orgs[slug],
                key=key,
                label=label,
                created_at=dt.datetime(2026, 1, 12, tzinfo=UTC),
                revoked_at=revoked_at,
                last_used_at=dt.datetime(2026, 4, 1, 23, 55, tzinfo=UTC),
            )

        # Overage webhooks. Nothing in the open tickets is about these; they are
        # here because the production logs mention them.
        endpoint = WebhookEndpoint.objects.create(
            organization=orgs["helio"],
            url="https://hooks.helio-robotics.example/meterly",
            secret="whsec_5b1c",
        )
        for day, code in [(19, 200), (24, 502), (24, 502), (24, 200), (29, 200)]:
            WebhookDelivery.objects.create(
                endpoint=endpoint,
                event_type="usage.overage",
                status_code=code,
                created_at=dt.datetime(2026, 3, day, 11, 5, tzinfo=UTC),
            )

        counts = {
            "organizations": Organization.objects.count(),
            "api keys": ApiKey.objects.count(),
            "invoices": Invoice.objects.count(),
            "usage records": UsageRecord.objects.count(),
        }
        for label, value in counts.items():
            self.stdout.write(f"  {value:>6}  {label}")
        self.stdout.write(self.style.SUCCESS("seed complete"))

    def _seed_usage(self, org, count, rng):
        """Spread `count` events across March 2026 for one organization."""
        records = []
        # Helio's 2026-03-18 backfill: 240 events written in one batch, all
        # stamped with the batch's start time rather than their own.
        backfill = 240 if org.slug == "helio" else 0

        for i in range(count):
            metric, unit_cost = METRIC_COSTS[i % len(METRIC_COSTS)]
            if i < backfill:
                recorded_at = BACKFILL_AT
            else:
                recorded_at = dt.datetime(2026, 3, 1, tzinfo=UTC) + dt.timedelta(
                    seconds=rng.randrange(0, 31 * 24 * 3600)
                )
            records.append(
                UsageRecord(
                    organization=org,
                    metric=metric,
                    quantity=rng.randrange(1, 400),
                    unit_cost_cents=unit_cost,
                    recorded_at=recorded_at,
                    external_id=f"evt_{org.slug}_{i:05d}",
                )
            )
        UsageRecord.objects.bulk_create(records, batch_size=1000)
