# Deploying the jobs bot on Dokploy

Unlike the scraper, which is a batch job on a cron, the bot is a **long-running
process**. It holds a Discord gateway connection and a MongoDB change stream, so
it must stay up; there is no schedule to configure.

It needs two databases: MongoDB (shared with the scraper, read-only) and
Postgres (its own, for thread bookkeeping).

## 1. Create the Postgres database

In Dokploy: **Project → Create Service → Database → PostgreSQL**.

Note the internal connection string Dokploy shows. It looks like
`postgresql://user:password@<service-name>:5432/<db>`. The bot creates its own
tables at startup, so no schema setup is needed.

## 2. Create the application

**Project → Create Service → Application**.

| Field | Value |
| --- | --- |
| Provider | GitHub → `monashcoding/jobs-bot` |
| Branch | `main` |
| Build type | Dockerfile |
| Dockerfile path | `Dockerfile` |

No domain and no port: the bot exposes no HTTP server, so leave the Domains tab
empty.

## 3. Environment variables

**Environment** tab. All three are required.

```
DISCORD_TOKEN=
MONGODB_URI=
DATABASE_URL=
```

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

`/jobs sync` refuses to run above `MAX_SYNC_JOBS` (300). If it aborts, the
scraper is marking far more listings eligible than intended — check that before
raising the limit.

## Notes

- **Eligibility is default-deny.** A listing with no `board_eligible` field is
  never posted. Nothing appears until the scraper has run with board scoring
  enabled, which is expected on a first deploy rather than a fault.
- **The change stream starts from now.** There is no resume token, so starting
  the bot does not replay history and cannot flood the forum with a backlog.
- **Time zone.** The container runs in UTC; the recap schedule names
  `Australia/Sydney` explicitly and the `tzdata` package ships the database, so
  the recap stays at 7pm local across daylight saving without a `TZ` variable.
- **Restarts are safe.** Thread bookkeeping lives in Postgres, so a restart
  re-registers pending views rather than reposting anything.
