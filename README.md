# Meterly — support escalation drill

Meterly meters usage for dev-tools SaaS customers. Their systems push usage
events into our public API all day; at month end we roll those events into an
invoice, apply credits, and bill the net. Customers read their own data back
through the API; our finance team reads the whole book through a dashboard.

It is the morning of **2 April 2026**. The March books closed yesterday.
**Four escalations are open. All four are real.** Your job is to reproduce each
one, find the cause, fix it, and be able to explain it out loud to the person
who reported it.

Budget **60 minutes** — roughly 12 minutes a ticket, leaving time to write up
your findings. If you are stuck past 15 minutes on one, move on and come back.
That decision is part of the drill.

---

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip

.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_demo
.venv/Scripts/python -m pytest -q                 # expect: 8 failed, 10 passed
.venv/Scripts/python manage.py runserver          # http://127.0.0.1:8000/
```

If you get anything other than **8 failed / 10 passed**, the environment is off.
Fix that before you start the clock.

Sign-ins are `mbell / meterly` (finance, superuser) and `rokafor / meterly`
(Helio Robotics' account owner). Live API keys are in
`core/management/commands/seed_demo.py`.

> **The test suite is not a map of the bugs.** One of these four tickets has no
> failing test at all. Three of them do. Which is which is for you to work out —
> a green suite is not the finish line.

`logs/app.log` is a slice of production logging over the period the tickets
cover. It is a second evidence channel, and for at least one ticket it is a
faster route in than the source.

---

## The rules the code is supposed to implement

This section is the **oracle**. When something looks wrong, the question is not
"what does the code do" but "what does this section say it should do."

**Billing.** An invoice's net is its gross minus any credit applied to it. An
invoice with no credit nets its full gross — "no credit" and "a zero credit"
mean the same thing to a customer. Every issued invoice for the period appears
in the summary, and the rows must add up to the reported total.

**Tenancy.** Every API response is scoped to the organization that owns the
credential on the request. No response may ever contain another organization's
data, for any length of time, under any circumstances.

**Authentication.** A request whose key is missing, unknown, or revoked is
answered with **401** and a `WWW-Authenticate` header naming the scheme. Client
SDKs treat 401 as "refresh credentials and retry" and 403 as "your key is fine
but you may not do this." A revoked key is revoked everywhere and for everyone.

**The usage feed.** `/api/v1/usage/` is served newest-first. A caller who walks
it from the first page to the last gets every record exactly once — none twice,
none skipped — **and ingestion does not pause while they walk it.**

---

## Open tickets

### TICKET-8880 — Corvid Labs — "We were looking at another company's account"
**Severity: critical.** Customer data exposure.

> Taro Nakamura, Platform Lead, Corvid Labs:
>
> "One of my engineers opened the usage summary yesterday afternoon and the
> panel said *Sundial Media* at the top with numbers about four times ours. He
> screenshotted it, called me over, hit refresh — and it was our own account
> again, correct. We tried for ten minutes and couldn't get it to happen again.
> Then this morning a different person on my team saw it once.
>
> I need to know whether anyone has been looking at *our* data the same way."

**Internal note (support):** Could not reproduce in staging. Both engineers were
on the same office network behind the same NAT, so this may be a proxy or a
browser-cache issue on their side rather than ours.

---

### TICKET-8814 — Helio Robotics — "Key rotation took our pipeline down for six hours"
**Severity: high.** Six hours of usage ingestion lost.

> Rina Okafor, Platform Engineering, Helio Robotics:
>
> "We rotated our API key on the 24th — minted the new one, moved the
> integration, revoked the old one. Standard.
>
> Except our sync service never noticed. Our SDK refreshes credentials and
> retries when it gets a **401**. Your API answered the revoked key with **403**,
> which our SDK treats as an authorization problem — not something a credential
> refresh fixes — so it stopped, logged, and paged whoever was on call. Nobody
> was, at 16:40 on a Tuesday. We lost six hours of events before anyone looked.
>
> Your docs say a revoked key gets a 401. It doesn't."

**Internal note (support):** Escalated once and bounced back. Our engineer
pasted the revoked key into the browser, hit `/api/v1/usage/`, and got a clean
**200 with data**. Marked not-reproducible. Customer pushed back, so reopening.

---

### TICKET-8871 — Finance (internal) — "The dashboard disagrees with the billing run"
**Severity: high.** Month-end close is blocked.

> Marcus Bell, Finance Ops:
>
> "The billing run issued 11 invoices for March: **$58,901.00 gross**,
> **$2,337.50 in credits**, **$56,563.50 net**. I have the run log.
>
> The revenue dashboard says **$33,762.00**. That's twenty-two thousand dollars
> missing. And four of the eleven customers have a blank dash where the amount
> should be — Vantage, Pallas, Northbeam, Ferrous.
>
> Those four are the ones with nothing in the credits column, so I assume their
> invoices failed to generate and that's why the total is short. Can we re-run
> the billing job for just those four?"

**Internal note (support):** Marcus's read seems right — the four blank rows are
exactly the four with no credits, so the credit step probably failed for them.
Suggest re-running the billing job for those accounts.

---

### TICKET-8884 — Helio Robotics — "Our nightly reconciliation never lands on the same number"
**Severity: medium.** Recurring, worsening.

> Tomas Lindqvist, Data Platform, Helio Robotics:
>
> "We walk `/api/v1/usage/` page by page every night and compare your event
> count to ours. It used to agree. Since about the 30th it never does, and it's
> a different number every night.
>
> Last night we ingested **4,812** events. Walking your feed returned **4,790
> unique IDs** — and along the way it handed us **31 records twice**. So we're
> short some records and duplicated others in the same run.
>
> Our own count is right; we checked it three ways. Is your feed dropping
> events, or is the pagination wrong?"

---

## What "done" looks like

1. **`pytest -q` is green** for the tickets that have tests. Do not edit a test
   to make it pass — fix the code underneath. And remember that green does not
   mean finished; one ticket's test does not exist.
2. **You can reproduce each bug before you fix it** — a `curl`, a shell one-liner,
   a click in the UI. Being able to *show* a bug is worth more than guessing it.
3. **You have written an escalation note for each ticket.** This is half the
   exercise.

```
REPRO:      the smallest exact sequence that shows the bug
IMPACT:     who is affected, how many, and what it costs them
HYPOTHESIS: the mechanism, stated so an engineer can confirm or kill it in one read
FIX:        what you changed, or what you'd propose and why
```

A good hypothesis names the **mechanism** ("the response is cached under a key
that doesn't include the tenant") rather than the symptom ("customers see the
wrong data"). Aim for that.

## Things worth noticing

- At least one internal note above points at the wrong layer.
- At least one ticket confidently asserts something that is not true, and
  proposes a fix that would not have helped.
- Two of these tickets produce the same one-line symptom as each other. So do
  the other two. Being able to say why the members of each pair are nothing
  alike is exactly what gets probed.
- After you fix something and a test goes green, ask what *else* could produce
  the same symptom before you move on.

## Stretch goals

- For TICKET-8880: write the query that establishes the blast radius. Who else
  could have seen whose data, and over what window?
- For TICKET-8880: draft the customer-facing RCA. Corvid asked a direct question
  about their own exposure and deserves a direct answer.
- For TICKET-8814: the fix has two parts and the first one alone still leaves
  the customer's SDK doing the wrong thing. Find both.
- For each ticket: name the **specific** guardrail that would have caught this
  before a customer did. Not "more tests" — the actual mechanism.

## When you're done

`SOLUTIONS.md` is the answer key: root cause per bug, a model escalation note,
notes on how to explain each one out loud, and a scorecard.

**Don't open it until you've finished or the hour is up.** Reading it early
costs you the entire value of the exercise.

To re-arm the drill after solving: `git checkout -- api billing core config`
