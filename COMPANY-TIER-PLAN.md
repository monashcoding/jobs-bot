# Handoff: move company prominence into the scraper

**For:** whoever owns the scraper (the Go repo holding `utils/companies.go`)
**From:** the Discord bot (`jobs-bot`)
**Status:** proposal, not started

## The problem

The weekly recap shows only 8 of the week's postings. The heading carries the
full count and the last line links the board, so those 8 slots decide what
people actually see — which means the bot now needs to know *which employers are
worth showing first*, not just which are worth posting.

The scraper's `notableCompanyNames` cannot answer that. It is a gate: a flat
`map[string]bool`, and every posting that reaches the recap has already passed
it. So the bot currently keeps a **second copy of the same ~278 names**, split
into tiers, in `src/core/functions/company_rank.py`.

Two hand-maintained lists in two repositories with nothing keeping them in step.
When the scraper adds a company, the bot posts it but ranks it below every named
employer, so in a busy week it never wins a slot — silently, with no error. The
bot has a drift checker (`scripts/check_company_drift.py`) that names the
difference, but that is a smoke alarm, not a fix.

The fix is for the scraper — which already owns the list — to emit the tier, and
for the bot to delete its copy.

## The contract

One new field on documents in the `active_jobs` collection, alongside the
`board_eligible` and `board_score` the scraper already writes:

```
company_tier: string    // "headline" | "major" | "unranked"
```

Set it wherever `board_score` is set today. Definitions:

| Value | Meaning |
|---|---|
| `headline` | The name alone makes someone open the message: big tech, the quant trading firms, bulge-bracket banks and Macquarie, MBB, and the AU names with the same pull (Atlassian, Canva, Airwallex, WiseTech, CommBank, Telstra, Qantas, BHP, CSIRO). |
| `major` | Everything else on the notable list: Big 4, remaining banks and insurers, mid-tier AU tech, telco and retail, defence and government, cyber, energy. |
| `unranked` | On the board but not classified. Should not occur while the tiers partition the list; exists so the field is always present and the bot never has to guess. |

### Why a string and not an int

Ints sort for free, which is the only argument for them. A string is readable in
Mongo and in logs without a legend, and inserting a tier later does not renumber
existing documents. Ordering is three lines in the consumer:

```python
_TIER_ORDER = {"headline": 0, "major": 1, "unranked": 2}
```

That map is a fixed, tiny thing. The 278-name list is not. Trading a free sort
for deleting the duplicate list is the whole point.

### Why not reuse `board_score`

Considered and rejected. `board_score` is a composite eligibility score — it
blends industry, discipline, recency and the rest — so a mediocre listing at a
headline firm can score below a strong one at an unknown employer, which is
exactly backwards for this use. It is also free to change scale whenever
eligibility tuning changes, and nothing would connect that change to the recap.
Prominence is a separate axis and deserves its own field.

## Scraper changes (Go)

Paths are inferred from the file we were shown; adjust to the real layout.

**1. Split the list, keep the gate byte-identical.**

In `utils/companies.go`, replace the single `notableCompanyNames` slice with one
slice per tier, and build the existing lookup map from all of them:

```go
var headlineCompanyNames = []string{ /* ... */ }
var majorCompanyNames = []string{ /* ... */ }

// companyTiers maps a normalised company key to its tier.
var companyTiers = map[string]string{}

func init() {
    for _, name := range headlineCompanyNames {
        if key := normaliseCompanyForMatching(name); key != "" {
            companyTiers[key] = TierHeadline
            notableCompanies[key] = true
        }
    }
    for _, name := range majorCompanyNames {
        if key := normaliseCompanyForMatching(name); key != "" {
            // First tier to claim a name keeps it, so a company listed twice
            // ranks by the better of the two.
            if _, seen := companyTiers[key]; !seen {
                companyTiers[key] = TierMajor
            }
            notableCompanies[key] = true
        }
    }
}

// CompanyTier reports how prominent an employer is, for ordering the board's
// weekly recap. IsNotableCompany still decides whether it appears at all.
func CompanyTier(name string) string {
    key := normaliseCompanyForMatching(name)
    if tier, ok := companyTiers[key]; ok {
        return tier
    }
    return TierUnranked
}
```

`notableCompanies` ends up holding exactly the same keys as before, so
`IsNotableCompany` and board eligibility do not change at all. **This must stay
true** — the tiering is an ordering change, and it should not move a single job
on or off the board. See verification below.

The tier assignments the bot is using today are in
`src/core/functions/company_rank.py` (`_HEADLINE_NAMES` / `_MAJOR_NAMES`) and
already cover all 278 names with no gaps. They are a starting point, not a
mandate — the scraper owns the list, so it owns the tiers.

**2. Write the field** in the board-scoring step that already sets
`board_eligible` and `board_score`, so a job is scored and tiered in one pass.

**3. Backfill `active_jobs`.** Every document that already has
`board_eligible: true` needs a `company_tier`, or the bot falls back to its local
list for the whole backlog. A one-off pass over the collection setting the tier
from the company name is enough; it is idempotent and can be re-run.

**4. One normalisation bug worth checking while you are in there.**
`normaliseCompanyForMatching` strips country and legal suffixes, but a name like
`"Commonwealth Bank of Australia"` loses the `Australia` and is left with a
dangling `of` → key `commonwealthbankof`, which matches nothing. The bare
`"Commonwealth Bank"` is also in the list so that specific employer is fine, but
any `X of Australia` with only the long form listed would be missed. The Python
side fixes this by adding trailing connectors (`of|the|and|&`) to the suffix
pattern and stripping repeatedly. Worth confirming against `StripCompanySuffix`,
which we have not read — this may already be handled.

## Bot changes (`jobs-bot`)

**1. Read the field.** `JobDocument` in
`src/backend/mongo/collections/col_jobs.py` gains:

```python
company_tier: str | None = Field(default=None)
```

**2. Carry it into Postgres.** `JobPost` in `src/backend/sql/models.py` gains the
same nullable field, and the mapping at `src/core/functions/job_post.py:208`
passes `company_tier=job.company_tier`. The recap reads `JobPost`, not Mongo, so
the value has to survive the denormalisation.

**3. Add the column.** There is no migration tool; add one line to
`_ADDITIVE_COLUMNS` in `src/backend/sql/client.py`:

```
"ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS company_tier VARCHAR",
```

Additive and nullable, which is the only kind of change that mechanism supports.

**4. Sort by it.** `recap_order` in `src/cogs/workers/weekly_recap.py` sorts on
`_TIER_ORDER.get(post.company_tier, 2)` instead of calling `company_rank`.

**Default semantics: missing tier sorts last, and logs at debug, not warning.**
This is deliberately unlike `is_board_eligible`, which is default-deny and warns
loudly. The asymmetry matches the one already documented in
`job_eligibility.py`: a missing `board_eligible` means the job was never scored
and posting it risks posting the entire collection, so it is refused. A missing
`company_tier` only means the bot does not know where to rank a job it has
already decided to post — the worst case is a good listing shown in position 9
instead of position 2. Failing closed there would silently drop real jobs out of
the recap to fix a cosmetic problem.

### No Postgres backfill is needed

The Mongo backfill above is required. A matching backfill of the `job_posts`
table is **not**, for a better reason than the one first given here.

`sync_jobs` only creates a `JobPost` for a `(job, guild)` pair that has no record
yet, so nothing re-posts an existing job. But the watcher's update path does
rewrite existing rows: `_handle_update` in `job_watcher.py` calls
`job_post_db.sync_fields(...)` for every Mongo update, refreshing the fields it
names. `company_tier` is now one of them.

That makes the scraper's first-run sweep do the backfill for us. Adding a field
changes every document's content hash, so the first scrape after the scraper
deploys emits an update for every job — and each of those updates writes the
tier into the corresponding `job_posts` row. By the end of that run the table is
current, with no script and no week of waiting.

It also means a **re-run of the scraper's tier backfill does reach already-posted
threads**. The corrected tier lands in Mongo, the change stream carries it, and
`sync_fields` applies it to rows whose threads already exist. The tier is a live
mirror, not a snapshot taken at post time.

`/jobs rebuild` remains safe for the original reason: it re-runs `sync_jobs`, so
recreated rows are built from Mongo and `restore_posted_at` puts the original
dates back afterwards.

**One operational note.** That first sweep is one update event per job, and
`_handle_update` does three Discord calls per posted job — `fetch_channel`,
`fetch_message`, `message.edit` — processed serially by the change-stream
consumer. On a board of a few thousand threads that is a long, rate-limited
burst, during which new inserts queue behind it. It is one-time and it is not a
fault, but deploy the scraper at a quiet hour and do not schedule anything else
against the bot that day.

## Rollout

The two repositories deploy independently, so this is sequenced to have no flag
day and no step that breaks the other side.

1. **Scraper ships the field and backfills.** The bot ignores unknown Mongo
   fields, so nothing changes for it yet. Safe to deploy alone.
2. **Bot reads the field with a fallback**: use `company_tier` when present, fall
   back to the local `company_rank` list when it is not. Both lists live for one
   release. Safe to deploy alone, in either order relative to step 1.
3. **Confirm no document that matters lacks the field** (query below).
4. **Bot deletes the fallback** and everything under "What gets deleted".

Steps 1 and 2 are independently reversible. Only step 4 is one-way, and it is
gated on step 3.

## Verification

**The gate did not move.** Before and after the Go change, on the same input:

```
db.active_jobs.countDocuments({ board_eligible: true })
```

must be identical. If it moved, the tier split changed what
`notableCompanies` contains, which it must not.

**Nothing eligible is untiered.** Gates step 4:

```
db.active_jobs.countDocuments({ board_eligible: true, company_tier: { $exists: false } })
```

must be 0. Worth adding to `src/core/functions/job_diagnostics.py`, which
already counts eligible, ineligible and unscored jobs — an untiered count
belongs in the same place.

**The recap still leads with the right names.** `tests/test_weekly_recap.py`
already asserts that a headline employer beats 20 tier-2 fillers to a slot; that
test should keep passing with the source of the tier swapped underneath it.

## What gets deleted when this lands

- `src/core/functions/company_rank.py` — the entire duplicate list, its
  normaliser, and the tier tables.
- `scripts/check_company_drift.py` and `scripts/__init__.py` — nothing left to
  drift.
- `tests/test_company_drift.py` — same.
- `tests/test_company_rank.py` — replaced by a much smaller test that the
  `_TIER_ORDER` map orders correctly.
- The `JOBS_SCRAPER_COMPANIES` env var and its mention in
  `company_rank.py`'s docstring.

Net: roughly 300 lines of duplicated data and its scaffolding, replaced by one
Mongo field and a three-entry dict.

## Open questions for the scraper team

1. Is `IsNotableCompany` the only company-based eligibility gate, or can a job
   be eligible without being on the list? If it can, `unranked` will occur in
   practice and is load-bearing rather than defensive.
2. Do you want the tier boundaries as proposed, or drawn differently? The bot has
   no opinion it is willing to defend here — it just needs *a* stable ordering
   that someone owns.
3. Is the backfill cheap enough to re-run on demand, or should the bot tolerate
   untiered documents indefinitely? That decides whether step 4 is a one-off or a
   standing condition.
