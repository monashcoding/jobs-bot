# Reply: company prominence has moved into the scraper

**For:** `jobs-bot`
**From:** the scraper (`mploy-golang-core`)
**Status:** scraper side built and green, not yet deployed
**Answers:** COMPANY-TIER-PLAN.md

Short version: the contract is implemented exactly as proposed. `company_tier`
is `"headline" | "major" | "unranked"`, written next to `board_score` on every
`active_jobs` document, and there is a backfill command for the existing
collection. Your step 2 can be written against it as specified.

The rest of this is the detail you need to sequence the rollout, plus three
things the plan did not anticipate.

## Your open questions

**1. Is `IsNotableCompany` the only company-based eligibility gate?**

Yes, and it is a hard gate — `board_scoring.go` refuses a listing whose employer
is not on the list, in the same block as discipline, location, role type and
application URL. Every board-eligible listing is therefore on the list, and the
two tier slices now cover the list exactly. So `unranked` is defensive, not
load-bearing: it cannot reach the recap. It is still always written, so the field
is never absent on a scored document and you never have to distinguish "not
tiered" from "not scored".

Two tests hold that shut from both directions: one asserts every key in the gate
map carries a tier, the other that every tiered key is in the gate map. A name
added to one list and not the other fails CI in this repo rather than silently
ranking last in yours.

**2. Tier boundaries?**

As proposed. I took `_HEADLINE_NAMES` / `_MAJOR_NAMES` verbatim — the split is
now 125 headline and 161 major, over 286 distinct keys. (Your doc says ~278; the
difference is normalisation, not names. See below.) The scraper owns them from
here, so send changes as an issue rather than editing a copy.

**3. Is the backfill cheap enough to re-run?**

Cheap: one projected pass over `active_jobs`, batched unordered bulk writes,
dry-run by default. It derives the tier from the stored company name, so it is
idempotent and correct to re-run after any edit to the tier lists.

    go run ./cmd/backfill-company-tiers            # dry run, prints the breakdown
    go run ./cmd/backfill-company-tiers -apply

**So step 4 is a one-off, not a standing condition** — but read "What re-running
the backfill does not fix" below before relying on that, because it does not
mean what it looks like it means on your side of the boundary.

## What shipped

Paths, since the plan guessed at them. The list is
`internal/utils/notable_companies.go`, not `utils/companies.go`.

- `internal/utils/notable_companies.go` — the single `notableCompanyNames`
  slice is now `headlineCompanyNames` and `majorCompanyNames`. `init()` builds
  both `notableCompanies` (the gate, unchanged in meaning) and `companyTiers`
  from them, first tier to claim a key winning. New: `TierHeadline`,
  `TierMajor`, `TierUnranked`, and `CompanyTier(name) string`.
- `internal/models/listing.go` — `CompanyTier string` with `bson:"company_tier"`.
- `internal/pipeline/steps/board_scoring.go` — `BoardVerdict.Tier`, set for
  every listing regardless of eligibility, and written onto the listing in the
  same loop as `BoardScore` and `BoardEligible`.
- `internal/pipeline/steps/mongodb_upload.go` — `company_tier` in the `$set`,
  inside the same guard as `board_score` and `board_eligible`. A partial run
  that skips board scoring writes none of the three rather than blanking them.
- `cmd/backfill-company-tiers` — the one-off pass.

`go vet ./...` and `go test ./...` are clean.

## Verification, as asked for

**The gate did not move.** Rather than compare `countDocuments` before and after
a deploy, I compared the thing that would cause it to move: the key set of
`notableCompanies`, dumped from the old code and the new one and diffed. Byte
identical, 286 keys both sides. No listing can move on or off the board as a
result of the split, so you do not need to hold a count across the deploy.

**Nothing eligible is untiered.** Held by the two partition tests above, plus a
test that walks real employers through `EvaluateForBoard` and asserts an
eligible verdict is never `unranked`. The backfill also reports it at runtime:
if any `board_eligible` document comes out unranked it warns and names the
employers, so a gap is diagnosable without a query.

Your gating query for step 4 should also catch a tier that is present but
empty or unranked, not only one that is absent:

```js
db.active_jobs.countDocuments({
  board_eligible: true,
  $or: [
    { company_tier: { $exists: false } },
    { company_tier: { $in: ["", "unranked"] } },
  ],
})
```

Both must be 0. The `$exists` form alone would pass a document the backfill
wrote as unranked, which is the case you actually care about.

## Three things the plan did not anticipate

### 1. The first run after deploy rewrites the whole collection

Expect a full change-stream sweep on the day the scraper deploys, and do not
read it as a fault.

The scraper skips writing a document whose content hash is unchanged, precisely
so a scrape does not rewrite every live thread. Adding `company_tier` to the
written fields changes that hash for every document, so the first run after
deploy touches all of them — one event per job, one thread re-render each. It
settles after that run and the hash goes back to suppressing no-op writes.

This is unavoidable for any new field and it is one-time, but it is thousands of
Discord API calls in a burst, so it is worth deploying the scraper at a quiet
hour rather than alongside anything else you want to watch.

### 2. Your `job_posts` tier is a snapshot, and the backfill cannot reach it

Your "No Postgres backfill is needed" section is right, and the reasoning holds.
But the same fact that makes it right — nothing rewrites a `JobPost` from Mongo
after creation — has a consequence worth writing down: the tier in Postgres is
whatever the Mongo document said **at post time**, and it never updates again.

So if the tier lists change later and the backfill is re-run, Mongo is corrected
but already-posted rows keep the old tier. Re-running the backfill is not a way
to fix the ordering of jobs already inside the current week's recap window. The
next posting from that employer gets the new tier, and within a week everything
the recap can reach is correct again — so this is a "wait a week" problem, not a
"run a script" one. `/jobs rebuild` is the escape hatch if it ever matters,
exactly for the reason your section gives.

That is my answer to question 3 in full: the backfill is cheap and re-runnable,
and it is authoritative for Mongo, but Mongo is not the whole story on your side.

### 3. `check_company_drift.py` will crash, not report

It regexes `notableCompanyNames = []string{...}`, which no longer exists. It
will exit with "Could not find `notableCompanyNames = []string{...}` in that
file" against the new source.

That matters for exactly one release — during step 2, while both lists are
alive. Two options:

- **Retire it early.** The scraper now owns the tiers and enforces the partition
  in its own tests, so the drift the script exists to catch cannot happen there
  any more. The only drift left is between your fallback copy and the scraper's
  list, for the one release the fallback lives.
- **Or patch the pattern** to `(?:headline|major)CompanyNames\s*=\s*\[\]string\{(.*?)\n\}`
  with `re.finditer`, unioning the two blocks. Roughly a three-line change, and
  the exit code keeps its meaning.

Retiring it is the honest option — it is scaffolding for a duplicate that is
about to be deleted — but patching it is cheap if you would rather not fly blind
through step 2.

## One deviation, deliberately

The plan's item 4 asked whether the dangling-connector bug was already handled in
`StripCompanySuffix`. It was not — `"Commonwealth Bank of Australia"` really does
reduce to `commonwealthbankof` and match nothing.

I fixed it, but **not** in `StripCompanySuffix`, which is where the plan pointed.
That function also feeds the stored company name and the listing fingerprint: an
employer whose long form is the canonical one would be renamed on the public job
board and re-keyed in Mongo, which is a migration with duplicate threads at the
end of it, not a bug fix. The connector strip is confined to
`normaliseCompanyForMatching`, where it only decides which spellings are the same
employer. Display names and fingerprints are untouched.

Effect: one listed key changes (`Reserve Bank of Australia`), long forms now
match their bare names, and the gate can only widen — never narrow — as a result.
It is why the key count is 286 rather than the 278 your doc quotes: our two
normalisers strip different things (yours also removes `group`, `technologies`,
`global`, `holdings`), so the same names collapse to slightly different numbers
of keys on each side. Nothing to reconcile — the count is an artefact of the
normaliser, and after step 4 there is only one of those left.

## What you can rely on

- `company_tier` is present on every document the scraper scores, always one of
  the three literals, never null and never absent.
- It is written in the same statement as `board_score` and `board_eligible`, so
  a document that has one has all three.
- It cannot be `"unranked"` on a document with `board_eligible: true`.
- The strings are the contract. If a tier is ever added or renamed here, that
  lands as a change to this document first.
