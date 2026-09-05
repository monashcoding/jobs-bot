# Deploying the jobs bot on Dokploy

Unlike the scraper, which is a batch job on a cron, the bot is a **long-running
process**. It holds a Discord gateway connection and a MongoDB change stream, so
it must stay up; there is no schedule to configure.

It needs two databases: MongoDB (shared with the scraper, read-only) and
Postgres (its own, for thread bookkeeping).

## 0. The Discord application

Needed once, before any of the below. At
<https://discord.com/developers/applications>:

1. **New Application**, then **Bot → Reset Token** and copy it. That token is
   `DISCORD_TOKEN` and is shown once.
2. No privileged intents are required. The bot runs on
   `discord.Intents.default()` and works entirely through slash commands, so
   leave Message Content, Presence and Server Members off.
3. **OAuth2 → URL Generator**: scopes `bot` and `applications.commands`;
   permissions **Manage Threads**, **Send Messages**, **Send Messages in
   Threads**, **Create Public Threads**, **Manage Messages**, **Embed Links**
   and **Add Reactions**. Open the generated URL to invite it.

Manage Threads is the one to check: without it the bot cannot archive, unarchive
or delete a post, so deadline closing and every reconciliation command fail.

## 1. Cut a release

Tag the commit you intend to run, so the deployed revision has a name:

```bash
git tag v1.1.0
git push origin v1.1.0
```

That triggers `.github/workflows/release.yml`, which publishes
`ghcr.io/monashcoding/jobs-bot` to the GitHub Container Registry.

Note that the compose route below **builds from the branch it is pointed at**:
`docker-compose.yml` declares `build: .` and no `image:`, so the published image
is a record of the release rather than what Dokploy runs. Point the service at
the tag (or at `main` once the tag is merged) so the two agree.

## 2. Create the service

The bot needs Postgres alongside it, and `docker-compose.prod.yml` describes
exactly that pairing -- the bot, a managed `postgres:16-alpine` with a
persistent volume, `restart: always` and log rotation.

In Dokploy: **Project → Create Service → Compose**.

| Field | Value |
| --- | --- |
| Provider | GitHub → `monashcoding/jobs-bot` |
| Branch | `main` |
| Compose path | `docker-compose.prod.yml` |

**One file, and it must be the prod one.** Dokploy accepts a single compose file
per service ([Dokploy/dokploy#1727](https://github.com/Dokploy/dokploy/issues/1727));
there is no field for a second. `docker-compose.prod.yml` is therefore complete
on its own rather than an overlay, so this is the whole stack:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Do not point Dokploy at `docker-compose.yml`. That is the development file: its
`db` service sits behind the `local-db` profile so a developer can use an
external database instead, and a profiled service does not start. Deploying it
would run the bot with no database, and `depends_on: required: false` means it
starts anyway and fails to connect rather than refusing.

The Application service type with **Build type: Dockerfile** also works if you
would rather manage Postgres separately: add a Dokploy PostgreSQL database and
point `DATABASE_URL` at its internal connection string.

No domain and no port either way: the bot exposes no HTTP server, so leave the
Domains tab empty.

## 3. Environment variables

**Environment** tab.

```
DISCORD_TOKEN=
MONGODB_URI=
POSTGRES_PASSWORD=
```

`docker-compose.prod.yml` builds `DATABASE_URL` from `POSTGRES_PASSWORD` and
points it at the bundled `postgres` service, so set the password rather than the
URL. Set `DATABASE_URL` yourself only if you took the Application route above
and provisioned Postgres separately.

Dokploy writes the Environment tab to a `.env` beside the compose file but does
not inject it into containers, so the compose file reads it back: `env_file`
picks up `DISCORD_TOKEN` and `MONGODB_URI`, and `${POSTGRES_PASSWORD}` is
interpolated from the same file. Nothing further is needed.

### MONGODB_URI needs the database name in the path

This is the one that bites. The **scraper** takes its database name from a
separate `MONGODB_DATABASE` variable, so its URI ends at the host:

```
mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
```

The **bot** reads the name from the URI path instead. Copy the scraper's URI
verbatim and the bot connects to an empty database called `bot`, watches a
collection that never changes, and posts nothing — with no error. Insert the
database name before the query string:

```
mongodb+srv://user:pass@cluster.mongodb.net/default?retryWrites=true&w=majority
                                            ^^^^^^^
```

Use whatever `MONGODB_DATABASE` is set to in the scraper's environment. The bot
logs `Connected to MongoDB database '<name>'` at startup — check it, and it
warns explicitly if the path was missing.

Change streams require a replica set. Atlas satisfies this; a standalone
`mongod` does not.

## 4. Deploy

Hit **Deploy**. A healthy start logs, in order:

```
Connecting to SQL database
SQL database ready
Connected to MongoDB database 'default'
Change stream open for collection=active_jobs
```

If the MongoDB line names a database you did not expect, fix `MONGODB_URI`
before going further — nothing will post.

## 5. Configure the Discord side

The bot does nothing until a guild is configured. Run these in the server, as a
user with the team role:

```
/jobs config set-forum-channel  #job-board        <- where job threads are created
/jobs config set-team-role      @Job Board Team   <- who can manage deletions
/jobs config set-role  Intern/Student  @Intern    <- mentioned in the weekly recap
/jobs config set-role  Graduate        @Graduate
/jobs config set-role  Professional    @Professional
/jobs config set-recap-channel  Internships           #intern-jobs
/jobs config set-recap-channel  Graduate/Professional #grad-jobs
```

Individual job posts do **not** mention a role. The only ping is the weekly
recap, posted Friday 7pm Sydney time, split into one message per audience. An
audience with no recap channel configured is skipped silently, so set both.

## 6. Verify

New jobs appear as forum threads when the scraper next runs and writes a
board-eligible listing. To check without waiting, `/jobs sync` reconciles
existing eligible jobs against the forum.

`/jobs sync` refuses to run when it would create more than `MAX_SYNC_JOBS` (300)
new threads in any one guild. The limit counts threads it would open, not the
size of the board, so reconciling a board larger than that stays possible, and
it is counted per guild because Discord's 1000-active-thread cap is a per-guild
budget. Archived threads do not count toward it. If it aborts, the log names
the guild and the count; the scraper is marking far more listings eligible than
intended — check that before raising the limit.

## When the board looks wrong

`/jobs diagnose` reports what the bot actually sees, because the likely causes
are indistinguishable from inside Discord and need different fixes:

- the MongoDB database it is connected to, and how many documents are in it
- eligible / not eligible / **never scored** counts — never scored means the
  scraper's board scoring has not run, which is not the same as being rejected
- of the eligible ones, how many are open, past their deadline, or outdated
- how many threads this server has recorded, and how many `/jobs sync` would
  create right now
- the most-represented employers among postable jobs, since several roles at one
  employer is normal and usually explains "duplicate companies"

Run it before `/jobs rebuild`. If `would create` is a handful and the forum
holds hundreds, the forum predates the filter and a rebuild is the fix. If
`would create` is itself huge, the filter is not the problem — check the scraper
before deleting anything.

Its presence is also the version check: if `/jobs diagnose` does not appear in
Discord, the running container predates it and none of the newer filtering is
deployed either.

## Rebuilding the board from scratch

`/jobs rebuild` deletes every job thread **and** its record in this server, then
re-posts the board-eligible jobs as new, empty threads. It needs the team role,
the same as the other job commands.

It exists because archiving cannot rebuild a forum: `/jobs sync` skips any job
that already has a `job_posts` record, so archiving everything and re-syncing
recreates nothing. The records have to go for the board to be rebuilt.

This is the one destructive command in the bot. Deleting a thread deletes what
people said in it, including anyone who came back to report an interview or an
offer, and archived threads are deleted too. It is gated three ways: the team
role, a typed `DELETE EVERYTHING` argument, and a button only the invoker can
press, which reports the thread count before anything happens. It is scoped to
the server it is run in.

What prevents an accident here is the phrase and the button rather than the
permission level, so it sits with the rest of the board tooling: the people who
run the board should not need an admin to fix their own forum.

Re-posted jobs keep their original posting date, so the weekly recap still
announces only what is genuinely new. Without that a rebuild would stamp the
whole board with today, and the next recap would present all of it as this
week's postings and ping every role about it.

Use `/jobs archive-all` instead if you only want the forum tidied — archived
threads are hidden from the forum view, keep their history, and do not count
toward Discord's active-thread limit.

## Notes

- **Eligibility is default-deny.** A listing with no `board_eligible` field is
  never posted. Nothing appears until the scraper has run with board scoring
  enabled, which is expected on a first deploy rather than a fault.
- **Closed roles are never posted.** A listing whose `close_date` has passed, or
  which is marked `outdated`, gets no thread — previously one was created and
  then immediately renamed, tagged Closed and archived by the deadline watcher.
  A listing with *no* deadline is still posted: rolling applications are common,
  so unlike eligibility this one is default-allow.
- **The change stream starts from now.** There is no resume token, so starting
  the bot does not replay history and cannot flood the forum with a backlog.
- **Time zone.** The container runs in UTC; the recap schedule names
  `Australia/Sydney` explicitly and the `tzdata` package ships the database, so
  the recap stays at 7pm local across daylight saving without a `TZ` variable.
- **Restarts are safe.** Thread bookkeeping lives in Postgres, so a restart
  re-registers pending views rather than reposting anything. The weekly recap
  records when it last ran per guild, so restarting inside the recap hour does
  not ping a second time.
