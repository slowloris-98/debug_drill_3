# SOLUTIONS — sealed answer key

**Stop here if the hour isn't up.** Reading this early costs you the exercise.

Every fix below was applied to a clean copy of this repo. The suite went from
**11 failed / 11 passed** to **22 passed**. No test was modified to get there.

Five bugs, spread across the areas the interview brief names: an HTTP/caching
bug, an auth-semantics bug, an ORM/NULL bug, a pagination bug, and a raw-SQL
range bug. Four have failing tests. **Bug 1 has none** — that is deliberate,
and the reason matters.

---

## Bug 1 — TICKET-8880 — a tenant-scoped response cached under a key that has no tenant in it

**Where:** `api/views.py`, `UsageSummaryView`:

```python
@method_decorator(cache_page(60), name="dispatch")
class UsageSummaryView(APIView):
```

**Reproduce** (needs the dev server; two requests inside 60 seconds):

```bash
curl -s -H "Authorization: Api-Key mk_live_helio_7f3a91c4e2"   localhost:8000/api/v1/summary/
curl -s -H "Authorization: Api-Key mk_live_vantage_4c1e77b930" localhost:8000/api/v1/summary/
# both return {"organization":"Helio Robotics", ...}
```

### Root cause — the cache key omits the thing that scopes the response

`cache_page` builds its key from the **request URL plus whatever headers the
response names in `Vary`**. The URL here is `/api/v1/summary/` for everybody.
The tenant is carried in `Authorization`, and the response's `Vary` is just
`Accept`. So the key is effectively constant across all eleven customers:
whoever misses first warms the cache, and for the next 60 seconds everyone else
is served that body.

| | What the caller sent | What they got |
|---|---|---|
| Vantage warms it, 14:03:55 | `Api-Key ...4c1e77b930` | Vantage Freight ✅ |
| Sundial, 14:04:11 | `Api-Key ...9d20b6f1a5` | **Vantage Freight** ❌ |
| Corvid, 14:04:29 | `Api-Key ...6e93b1d284` | **Vantage Freight** ❌ |
| Corvid, 14:06:02 (after expiry) | `Api-Key ...6e93b1d284` | Corvid Labs ✅ |

That is the whole shape of the complaint: wrong for up to a minute, right on
the next refresh, impossible to reproduce on demand. `logs/app.log` around
`2026-04-01 14:03–14:06` shows it directly — a run of `cache=HIT` for orgs that
never logged a `cache=MISS` of their own.

### The fix, in two stages — and the first stage is not enough

The stage-one fix makes the symptom go away:

```python
from django.views.decorators.vary import vary_on_headers

@method_decorator(cache_page(60), name="dispatch")
@method_decorator(vary_on_headers("Authorization"), name="dispatch")
class UsageSummaryView(APIView):
```

The response now varies by credential, so our own cache stops crossing tenants.
**But `cache_page` still emits `Cache-Control: max-age=60` with no `private`.**
That is an instruction to every intermediary — CDN, corporate proxy, the
browser's shared cache — that this body is fine to store and re-serve. `Vary`
mitigates that only as far as each hop honours it, and `Vary: Authorization` on
a public response is exactly the pattern shared caches get wrong.

The answer that separates an L2 from an L1: **a per-tenant response does not
belong in a URL-keyed shared cache at all.** Cache the expensive aggregate under
a key you control, and mark the response uncacheable by anyone else:

```python
from django.core.cache import cache
from django.views.decorators.cache import never_cache

@method_decorator(never_cache, name="dispatch")
class UsageSummaryView(APIView):
    def get(self, request):
        organization = resolve_organization(request)
        key = f"usage-summary:{organization.pk}"
        payload = cache.get(key)
        if payload is None:
            payload = self._build(organization)
            cache.set(key, payload, 60)
        return Response(payload)
```

The tenant is now *in the key*, not hoped for in a header.

### Why no test caught it

`config/settings.py`:

```python
TESTING = "pytest" in sys.modules or "test" in sys.argv
CACHES = {"default": {"BACKEND": "...DummyCache" if TESTING else "...LocMemCache"}}
```

The suite runs against a cache backend that stores nothing. **The test
environment disables the thing that broke.** This is an extremely common real
setup and worth saying out loud — "we couldn't have caught this, and here's the
specific reason" is a better answer than "we should add a test."

The test that does catch it has to turn caching back on:

```python
@override_settings(CACHES={"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_two_tenants_never_share_a_cached_summary(api_client):
    first = api_client.get("/api/v1/summary/", **auth(HELIO_KEY)).json()
    second = api_client.get("/api/v1/summary/", **auth(VANTAGE_KEY)).json()
    assert first["organization"] == "Helio Robotics"
    assert second["organization"] == "Vantage Freight"
```

### What was a red herring

The support note blames the customer's network — "same office, same NAT, maybe
a proxy or browser cache." It is pointing one layer too far out. It is *almost*
right, which is what makes it dangerous: the mechanism genuinely is HTTP
caching, just ours rather than theirs. Chasing the customer's browser would
have burned the afternoon.

### Blast radius — the honest answer

There is **no database record of who saw what**. Every affected read was a cache
hit; it never touched a row, so nothing was written down. The only evidence is
`logs/app.log`, and it only covers what we happened to log. Say that plainly —
"I can bound it from the logs but I cannot prove it from the data" is the
correct and more valuable answer. From the logs: any org logging `cache=HIT` on
`/api/v1/summary/` within 60s of a different org's `cache=MISS`, for as long as
the decorator has been in place.

### Escalation note

```
REPRO:      GET /api/v1/summary/ with Helio's key, then the same URL with
            Vantage's key inside 60s. Both return Helio's body.
IMPACT:     All 11 organizations, on the summary endpoint only, for up to 60s
            after any cache miss. Customer-visible cross-tenant data exposure.
            No writes were affected and no data was altered.
HYPOTHESIS: cache_page keys on URL + Vary headers. The tenant is in the
            Authorization header, which is in neither, so one cached body is
            served to every caller for the TTL.
FIX:        Cache per-organization under an explicit key and mark the response
            private/no-store. Vary: Authorization alone is insufficient because
            the response still advertises itself as publicly cacheable.
```

### Saying it out loud

> "The summary response was being cached under the URL alone. The URL is the
> same for every customer — what makes it yours is the API key in the header,
> and the cache never looked at that. So for up to a minute after any customer
> loaded the page, everyone else loading it got that customer's copy. It fixed
> itself on the next refresh, which is why it looked random. No data was
> changed and nothing was written to the wrong account — it was a read-side
> exposure, and I can tell you from the logs which accounts were served
> someone else's summary."

---

## Bug 2 — TICKET-8814 — authentication that declines instead of rejecting

**Where:** `api/authentication.py`, `ApiKeyAuthentication`, plus
`DEFAULT_AUTHENTICATION_CLASSES` in `config/settings.py`.

**Reproduce:**

```bash
curl -i -H "Authorization: Api-Key mk_live_helio_0b52d8aa16" localhost:8000/api/v1/usage/
# HTTP/1.1 403 Forbidden        <- docs promise 401
# (no WWW-Authenticate header)
```

### Root cause, part one — `return None` means "not mine," not "denied"

```python
except ApiKey.DoesNotExist:
    return None
if api_key.revoked_at is not None:
    return None
```

In DRF, an authenticator returning `None` is saying *"this credential isn't
mine to judge — try the next one."* It is the correct response to a missing or
foreign header, and the **wrong** response to a credential that is ours and is
bad. So the request falls through to the next authenticator in the list:

```python
"DEFAULT_AUTHENTICATION_CLASSES": [
    "api.authentication.ApiKeyAuthentication",
    "rest_framework.authentication.SessionAuthentication",
],
```

A browser with a live dashboard session authenticates on the session cookie and
gets **200 with data** — which is precisely what our engineer did on the 24th
before marking the ticket not-reproducible (`logs/app.log`, 19:12–19:14). The
key was never accepted; the session rescued the request. From the outside those
are indistinguishable.

### Root cause, part two — no `authenticate_header()`, so 401 silently becomes 403

**Raising `AuthenticationFailed` does not fix the status code.** DRF converts a
401 into a 403 whenever the first authenticator's `authenticate_header()`
returns `None`, because a 401 without a `WWW-Authenticate` header is malformed
under RFC 7235. `BaseAuthentication.authenticate_header()` returns `None`, and
this class never overrode it.

Measured on this repo, all three variants:

| `authenticate()` on a bad key | `authenticate_header()` | Status | `WWW-Authenticate` |
|---|---|---|---|
| `return None` (shipped) | not defined | **403** | absent |
| `raise AuthenticationFailed` | not defined | **403** | absent |
| `raise AuthenticationFailed` | defined | **401** | `Api-Key realm="api"` |

The middle row is the trap. It fixes the session fall-through, makes
`test_a_revoked_key_is_not_rescued_by_a_signed_in_browser_session` pass, and
leaves the customer's SDK doing exactly the wrong thing. If you stopped there,
you shipped Rina's outage back to her.

### Fix

```python
from rest_framework.exceptions import AuthenticationFailed

        except ApiKey.DoesNotExist:
            raise AuthenticationFailed("Unknown API key.")

        if api_key.revoked_at is not None:
            raise AuthenticationFailed("This API key has been revoked.")

    def authenticate_header(self, request):
        return f'{KEYWORD} realm="api"'
```

Also worth proposing: drop `SessionAuthentication` from the API defaults. Once
we raise, it is unreachable for a bad key — but leaving a second way to
authenticate a public API endpoint means the next mistake in this file has the
same silent fallback waiting behind it. Defence in depth, and it is why the
engineer's manual test lied.

### Follow-ups they may ask

- *"Why is 401 vs 403 worth an outage?"* They are different instructions.
  401 = "your credentials are the problem, get new ones and retry" — a
  self-healing client behaviour. 403 = "your credentials are fine, you may not
  do this" — retrying is pointless, so a correct client escalates to a human.
  Returning 403 for a revoked key tells every well-behaved SDK to stop trying.
- *"How would you find other customers hit by this?"* Group `logs/app.log` by
  key for 403s from non-browser user agents; cross-reference `ApiKey.revoked_at`.
- *"Why didn't the tests catch it?"* They did — four of the eight failures are
  in `tests/test_api_auth.py`. This one wasn't invisible; it was closed as
  not-reproducible on a manual test that was quietly authenticating a different
  way.

### Escalation note

```
REPRO:      curl -i -H "Authorization: Api-Key <revoked>" /api/v1/usage/
            -> 403, no WWW-Authenticate. Docs and SDK both expect 401.
IMPACT:     Every customer who rotates a key. Helio lost ~6h of ingestion on
            2026-03-24. Anyone whose client refreshes on 401 fails the same way.
HYPOTHESIS: The authenticator returns None on a bad key rather than raising, so
            requests fall through to SessionAuthentication; and it defines no
            authenticate_header(), which makes DRF downgrade 401 to 403.
FIX:        Raise AuthenticationFailed on unknown/revoked keys AND implement
            authenticate_header(). Remove SessionAuthentication from the API
            defaults so there is no silent second path.
```

### Saying it out loud

> "Two things went wrong and you only saw the second. Our code treated your
> revoked key as *unrecognised* rather than *rejected*, so the request fell
> through to a second authentication method — that's why our engineer's browser
> test came back 200 and we closed your ticket. And because our authenticator
> never advertised a challenge scheme, the framework downgraded the 401 to a
> 403, which is what stopped your SDK from retrying. Both are fixed; a revoked
> key now returns 401 with a `WWW-Authenticate` header, and I'm sorry we bounced
> this back to you the first time."

Leading with *"we closed your ticket wrongly, and here's the mechanism that
fooled us"* rather than with the status code is the instinct being tested.

---

## Bug 3 — TICKET-8871 — NULL propagating through an arithmetic expression

**Where:** `billing/reports.py`, both `invoice_summary()` and `revenue_total()`.

```python
.annotate(net_cents=F("gross_cents") - F("credit_cents"))
```

**Reproduce:**

```bash
python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup(); \
import datetime as dt; from billing.reports import revenue_total; print(revenue_total(dt.date(2026,3,1)))"
# 3376200      <- finance signed off on 5656350
```

### Root cause — `x - NULL` is `NULL`, and `SUM` skips NULLs

Four March invoices have `credit_cents = NULL`, not `0` — the billing importer
has always written NULL when no credit was issued (`core/models.py` says so in
a comment; `seed_demo.py` names the four accounts).

In SQL, any arithmetic involving NULL yields NULL. So for those four rows
`gross - credit` is NULL, and **one cause produces two symptoms that look
unrelated**:

1. The dashboard renders a blank dash where the amount should be.
2. `SUM()` ignores NULL inputs entirely, so those four invoices contribute
   *nothing* to the total — not zero, absent.

| | Reported | Truth |
|---|---|---|
| March net revenue | $33,762.00 | **$56,563.50** |
| Missing | $22,801.50 | — |
| Invoices with no net | 4 | 0 |

And $22,801.50 is exactly Vantage + Pallas + Northbeam + Ferrous
(968,500 + 610,750 + 412,300 + 288,600 = 2,280,150 cents). The shortfall equals
the gross of the blank rows — that arithmetic is the confirmation.

### Fix

```python
from django.db.models import F, IntegerField, Sum, Value
from django.db.models.functions import Coalesce

NET_CENTS = F("gross_cents") - Coalesce(
    F("credit_cents"), Value(0), output_field=IntegerField()
)
```

then `.annotate(net_cents=NET_CENTS)` in both functions.

The better structural fix, which you should *propose* rather than do under the
clock: `credit_cents` should be `NOT NULL DEFAULT 0` with a data migration
backfilling the NULLs. "No credit issued" and "a credit of zero" are the same
business fact, and storing them as different values guarantees this class of bug
recurs everywhere the column is used. Patching each query is treating symptoms.

### What was a red herring

**Marcus's diagnosis is wrong, and his proposed fix would have made it worse.**
He observed that the four blank rows are exactly the four with no credits and
concluded their invoices failed to generate. They generated fine — all eleven
are in the database with correct gross figures. Re-running the billing job for
those four accounts would have done nothing at best; at worst it would have
double-issued four invoices while the report still read $33,762.

The support note repeats his theory back to him. Both are downstream of the
same coincidence: the four affected rows *are* the four with no credit — that
correlation is real, and the causal story attached to it is not.

Test `test_all_eleven_invoices_appear_in_the_summary` passes throughout,
before and after. That is the evidence that kills Marcus's hypothesis in one
line, and it was sitting in the suite the whole time.

### Escalation note

```
REPRO:      revenue_total(2026-03-01) returns 3376200; the billing run issued
            5656350. invoice_summary() returns net_cents=None for 4 of 11.
IMPACT:     Every month-end close, every period, for every invoice with no
            credit. March understated by $22,801.50. Reporting only — the
            invoices themselves and what customers were billed are correct.
HYPOTHESIS: net is computed as gross - credit with credit NULL on 4 invoices.
            NULL arithmetic yields NULL, so those rows render blank, and SUM
            skips NULL inputs so they contribute nothing to the total.
FIX:        Coalesce(credit_cents, 0) in both report queries; separately,
            migrate credit_cents to NOT NULL DEFAULT 0 so this cannot recur.
```

### Saying it out loud

> "The invoices are all correct and every customer was billed the right amount —
> this is a reporting bug only. Four invoices had no credit applied, and we
> store 'no credit' as an empty value rather than as zero. Subtracting an empty
> value from a number gives you an empty value, and our total quietly skips
> empty values instead of counting them as nothing. So those four dropped out of
> the sum, which is why the report is short by exactly their combined amount.
> Nothing needs re-running."

Leading with *"the invoices are correct, this is reporting only"* is the part
that matters to Marcus — he is deciding whether to re-run a billing job against
real customers. Answer that first.

---

## Bug 4 — TICKET-8884 — offset pagination over a feed that is still being written

**Where:** `api/pagination.py` (`PageNumberPagination`) and
`core/models.py` (`UsageRecord.Meta.ordering = ["-recorded_at"]`).

**Reproduce:**

```bash
A="Authorization: Api-Key mk_live_helio_7f3a91c4e2"
curl -s -H "$A" "localhost:8000/api/v1/usage/?page=1" | grep -o '"id":[0-9]*' | tail -2
#   "id":1090 "id":2794
curl -s -X POST -H "$A" -H "Content-Type: application/json" \
  -d '{"external_id":"evt_x","metric":"api_calls","quantity":9,"unit_cost_cents":2,"recorded_at":"2026-04-02T12:00:00Z"}' \
  localhost:8000/api/v1/usage/
curl -s -H "$A" "localhost:8000/api/v1/usage/?page=2" | grep -o '"id":[0-9]*' | head -2
#   "id":2794 "id":1068      <- 2794 served twice
```

### Root cause — `LIMIT/OFFSET` addresses positions, and the positions move

`?page=2` becomes `LIMIT 50 OFFSET 50`: *skip the first fifty rows of the
current result*. It does not mean "the fifty after the ones you already saw."
The feed is sorted newest-first and Helio ingests continuously, so **every event
that arrives mid-walk pushes the whole list down by one**. The record that was
position 50 becomes position 51 and is served again as the first row of page 2.

That accounts for the duplicates. The *missing* records are the same mechanism
seen from the other end: because the feed is newest-first, an event that arrives
after page 1 has been read is inserted **above** the walk, at a position the
walker has already gone past. It is never returned. So one mechanism produces
both halves of Tomas's complaint at once — every mid-walk arrival is one record
duplicated at a page boundary *and* one record never delivered:

| Night | Ingested | Unique IDs returned | Duplicates |
|---|---|---|---|
| 03-29 | quiet period | 4,812 | 0 |
| 03-30 | busy | 4,846 | 31 |
| 04-02 | busy | 4,790 | 31 |

The 03-29 clean run is the tell: the bug only shows when ingestion overlaps the
walk. That is also why it "used to agree."

**A second, independent defect in the same place:** `recorded_at` is not unique
and is not backed by a tiebreaker. 240 of Helio's records are a backfill batch
that all carry `2026-03-18T02:00:00Z` (see `seed_demo.py`). The database is free
to order tied rows differently between queries, so even a perfectly quiet feed
can shuffle rows across a page boundary. **Ordering by a non-unique column is
never a stable pagination key.**

### Fix

Adding a tiebreaker is necessary and **not sufficient** — it fixes the ties and
does nothing about the drift. The correct fix is to stop addressing positions
and start addressing records:

```python
# api/pagination.py
from rest_framework.pagination import CursorPagination

class UsagePagination(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
    ordering = ("-recorded_at", "-id")
```

```python
# core/models.py
class Meta:
    ordering = ["-recorded_at", "-id"]
```

A cursor encodes *where you were* rather than *how many to skip*, so rows
arriving above your position cannot shift you, and the duplicates stop. The
`-id` tiebreaker is what makes the cursor well-defined when timestamps tie — the
two fixes are not alternatives, the cursor requires the tiebreaker to be correct.

**Be precise about what the cursor does not fix.** It stops the duplicates. It
does not make events that arrive above your position appear — no walk of a live,
newest-first feed can, because the thing you are walking keeps growing at the
end you already passed. For *reconciliation* the answer is to stop walking a
moving target and walk a bounded window instead:

```python
# GET /api/v1/usage/?recorded_before=2026-04-02T00:00:00Z
qs = qs.filter(recorded_at__lt=recorded_before)
```

Now the result set is closed, and cursor pagination walks it exactly once.
Saying "cursor pagination, *plus* a bound, because otherwise you are reconciling
against a set that is still growing" is the complete answer.

The `Meta.ordering` change generates a migration
(`0002_alter_usagerecord_options.py`, an `AlterModelOptions`). Run
`makemigrations` — it is metadata only, no table is rewritten.

### The part worth raising unprompted

**This is a breaking API change.** Tomas's job calls `?page=2`; cursor
pagination replies with opaque `next` URLs and drops `count`. Shipping it
silently trades a data bug for an integration outage. Say so, and propose the
path: version the endpoint or keep page-number pagination working for a
deprecation window, and tell customers to follow the `next` link rather than
constructing page numbers.

If a breaking change is off the table, the snapshot bound above is most of the
fix on its own: with `recorded_before` pinned, offsets stop drifting because the
set stops growing, and the `-id` tiebreaker handles the ties. That is a
legitimate answer and a smaller blast radius. The test suite here is written to
the cursor fix, so that is the one that turns it green.

### Follow-ups they may ask

- *"Are we actually losing their events?"* No. Ingestion is fine — 4,812 events
  are in the table and `POST` returned 201 for all of them. This is purely a
  read-path bug. Answer this first; it is what Tomas asked.
- *"Why did it start on the 30th?"* It didn't. It started whenever their
  ingestion volume grew enough to overlap the reconciliation window.
- *"How do you detect this class of bug?"* DRF raises
  `UnorderedObjectListWarning` for a genuinely unordered queryset — but not
  here, because the queryset *is* ordered, just not uniquely. That is why the
  warning did not fire and why this survived review.

### Escalation note

```
REPRO:      GET /api/v1/usage/?page=1, POST one new usage event, then
            GET ?page=2. The last id of page 1 is the first id of page 2.
IMPACT:     Any customer walking the feed while ingesting. Helio's nightly
            reconciliation: 31 duplicated and ~22 missed records per run.
            Read path only — no events were lost or double-billed.
HYPOTHESIS: Page N is LIMIT/OFFSET over a descending live feed. Each event
            arriving mid-walk shifts every subsequent offset by one, repeating
            a row at the page boundary, and lands above the walk position so it
            is never returned. Separately, recorded_at is non-unique with no
            tiebreaker, so tied rows can reorder between queries.
FIX:        Cursor pagination ordered by (-recorded_at, -id), plus a
            recorded_before bound so reconciliation walks a closed set. Note
            the cursor change breaks clients constructing ?page=N and needs a
            deprecation window.
```

### Saying it out loud

> "Nothing is being dropped — all 4,812 of your events are stored, and this is
> only about how we hand them back. Asking for page 2 means 'skip the first
> fifty rows', and the feed is newest-first, so every event that lands while
> you're paging pushes everything down by one. A record that was the last row of
> page 1 becomes the first row of page 2 and you see it twice. And the new event
> itself lands at the top of the list — above the point you'd already read past —
> so you never see that one at all. Same shift, both symptoms: one record
> duplicated and one record missed, every time an event arrives mid-walk. That's
> why your count is wrong in both directions on the same run, and why it agreed
> on quiet nights."

---

## Bug 5 — TICKET-8892 — `BETWEEN` two dates on a timestamp column

**Where:** `billing/usage_rollup.py`, `ROLLUP_SQL`:

```sql
WHERE u.recorded_at BETWEEN %s AND %s
```

called as `usage_rollup(date(2026, 3, 1), date(2026, 3, 31))`.

**Reproduce:**

```bash
python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup(); \
import datetime as dt; from billing.usage_rollup import period_totals; print(period_totals(dt.date(2026,3,1), dt.date(2026,3,31)))"
# {'events': 7934, ...}      <- 8,182 events were ingested in March
```

Or open `/usage/` and read the footer: 7,934.

### Root cause — the upper bound is a date, and the column is a timestamp

`BETWEEN a AND b` is `>= a AND <= b`. The parameter `2026-03-31` is a *date*;
compared against a timestamp column it means the **first instant** of that day,
`2026-03-31 00:00:00`. So the filter is:

```
recorded_at >= 2026-03-01 00:00:00  AND  recorded_at <= 2026-03-31 00:00:00
```

Everything on the 31st after midnight — 23 hours, 59 minutes and 59 seconds of
it — falls outside. **248 events across all eleven customers, every month.**

| | Rolled up | Actual |
|---|---|---|
| March events, all customers | 7,934 | **8,182** |
| Sundial Media, each metric | 147 / 148 / 152 / 153 | **155 each** |
| Sundial build minutes | 28,314 | **29,824** |

Jo's arithmetic is exactly right, including the part she was least sure about:
every metric is light, not just build minutes, because the missing day is
missing for all of them.

`logs/app.log` states it outright if you look —
`2026-04-01 10:12:34 WARN meterly.billing rollup_events=7934 ingested_events=8182 delta=-248`,
sitting directly under an ingest line confirming 248 events accepted on the 31st.

### Fix — a half-open interval, not an inclusive one

```python
     WHERE u.recorded_at >= %s AND u.recorded_at < %s
```

```python
        # The period is inclusive of its last day, so the exclusive upper
        # bound is the first instant of the next day.
        cursor.execute(ROLLUP_SQL, [period_start, period_end + dt.timedelta(days=1)])
```

**Do not fix this by writing `BETWEEN %s AND %s` with `'2026-03-31 23:59:59'`.**
It is the fix people reach for and it is wrong in two ways: it silently drops
anything in the last second (sub-second precision is real — `recorded_at` is
stored to the microsecond), and it breaks the moment the column type changes or
the database rounds differently. `>= start AND < next_start` is correct at every
precision and needs no arithmetic on the boundary value.

The general rule worth stating: **date ranges over timestamps are half-open.**
Inclusive upper bounds on a continuous quantity are always a bug waiting for a
finer clock.

### The suite rejects the shortcut

Worth knowing before you reach for `23:59:59`: it does not go green. Sundial's
final March event is stamped `2026-03-31 23:59:59.500000` (the seed says so),
so an inclusive `23:59:59` bound still loses it — and all three rollup tests
still fail, not just one:

| Predicate | March | April | Total (8,237 stored) |
|---|---|---|---|
| `BETWEEN date AND date` (shipped) | 7,934 | 0 | 7,934 |
| `BETWEEN … AND '…23:59:59'` | 8,181 | 55 | **8,236** |
| `>= start AND < next start` | 8,182 | 55 | **8,237** ✅ |

`test_march_and_april_together_account_for_every_event` is the one that pins it
down: March's count plus April's count must equal every stored event, so no
event may fall between two consecutive periods. That single invariant is worth
more than either of the two absolute-number tests, because it keeps holding
when the seed data changes.

### What was a red herring

The support note guesses timezones — "Sundial are UK-based and we store
everything in UTC." Plausible, and wrong. A timezone error shifts a boundary by
a fixed offset and would move *some* of the 31st out and *some* of the 1st in;
this loses the entire 31st and gains nothing. **A timezone bug displaces a
window. This one truncates it.** That distinction is worth being able to make
quickly, because the two get confused constantly.

The other tempting wrong turn is ingestion: Jo says the numbers are short, so
did we drop the events? No — `POST` returned 201 all through the 31st and the
rows are in the table. This is entirely a read-path bug, and confirming that
first is what stops you debugging the wrong service.

### Escalation note

```
REPRO:      period_totals(2026-03-01, 2026-03-31) returns 7,934 events;
            8,182 events are stored with a March recorded_at. The 248-event
            difference is every event on the 31st after 00:00:00.
IMPACT:     Every customer, every billing period, since this query shipped.
            Usage under-reported by one day per month — Sundial by 1,510 build
            minutes in March. Customers are under-billed and the usage report
            contradicts the usage feed.
HYPOTHESIS: BETWEEN is inclusive on both ends and the upper bound is a date, so
            it resolves to 2026-03-31 00:00:00 against a timestamp column. The
            last day is excluded except for anything landing exactly at midnight.
FIX:        Half-open range: recorded_at >= period_start AND recorded_at <
            period_end + 1 day. Not '23:59:59', which loses sub-second events.
```

### Saying it out loud

> "You're right, and thank you for checking — the missing minutes are exactly
> the 31st. We asked our database for usage 'between the 1st and the 31st', but
> because your events are stamped with a time and not just a date, 'the 31st'
> was read as the very start of that day. So everything you ran after midnight
> on your last day fell outside the report. It affects every metric and every
> customer, not just you, and it's a reporting error — the events themselves
> were all received and stored correctly. We'll correct your March figure and
> tell you what it should have been."

Volunteering the blast radius — *every customer, every month* — before Jo has to
ask is the difference between answering a ticket and handling an incident.

---

## The symptom collisions

These were built in deliberately. Interviewers probe exactly here.

**"Authentication did something strange"** — bugs 1 and 2. Bug 1 is a *read*
that returned someone else's data to a correctly authenticated caller: auth
worked, the cache didn't. Bug 2 is a caller who was never authenticated at all
and got the wrong *word* for it. One is a tenancy failure, the other is a status
code failure. Neither is "the API key system is broken."

**"The number is wrong"** — bugs 3, 4 and 5, in three different layers.

- **Bug 3** is wrong by a *set of rows*: four invoices contribute nothing. Same
  $33,762.00 every run. The defect is in an expression — NULL arithmetic.
- **Bug 5** is wrong by a *slice of time*: one day is missing from every period.
  Same 7,934 every run. The defect is in a predicate — an inclusive upper bound
  on a timestamp.
- **Bug 4** is wrong by a *different amount every run*. The defect is not in the
  query at all; it is in the interaction between a correct query and concurrent
  writes.

The first discrimination is stability: **if a wrong number is the same wrong
number twice, it is a logic bug; if it moves, something is changing underneath
you.** That splits bug 4 off immediately. The second is *what shape* is missing —
whole rows or a time slice — which splits 3 from 5. Have both sentences ready.

It is also worth noticing what 3 and 5 have in common and refusing to merge
them: both are month-end, both under-report, both are read-path only, and they
are in different files with unrelated causes. Fixing either one moves the other
not at all.

---

## Scorecard

| | Bug 1 (cache) | Bug 2 (auth) | Bug 3 (NULL) | Bug 4 (paging) | Bug 5 (range) |
|---|---|---|---|---|---|
| Found it from the symptom, not by grepping | | | | | |
| Quoted the rule from README before editing | | | | | |
| Reproduced it before fixing | | | | | |
| Checked for a second cause after the first fix | | | | | |
| Rejected the wrong theory in the ticket | | | | | |
| Explained it to the customer without jargon | | | | | |
| Named the guardrail, not "more tests" | | | | | |

- **Bug 1** is the one with no failing test. If you only worked the suite, you
  never opened it — and it is the highest-severity ticket of the five.
- **Bug 2** is the one where the obvious fix goes green and still ships the
  customer's outage back to them.
- **Bug 3** is the one where the reporter's own diagnosis is wrong and his
  proposed remedy would have touched live billing.
- **Bug 4** is the one where the correct fix is a breaking API change, and
  saying so unprompted is most of the signal.
- **Bug 5** is the one where the fix everyone reaches for (`23:59:59`) is also
  wrong, and where the customer has already done the diagnosis for you — the
  test is whether you take the gift and then check the blast radius anyway.

## Retro

- Did you find each one from the **symptom**, or by grepping for something
  suspicious?
- Did you **verify** each fix, rather than trusting a green test?
- For each bug, can you explain the root cause to the customer in two sentences
  with no jargon?
- Which two tickets did you nearly merge into one, and what told you they were
  different?

## A harder second pass

Re-arm with `git checkout -- api billing core config`, then delete the `tests/`
directory and work the five tickets from the complaints and `logs/app.log`
alone. That is the version of this that matches the actual job.
