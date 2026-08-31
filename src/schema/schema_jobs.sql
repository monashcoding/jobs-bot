-- Reference DDL for job_guild_configs and job_posts tables.
-- SQLModel generates these automatically at startup via SQLModel.metadata.create_all.

CREATE TABLE IF NOT EXISTS job_guild_configs (
    guild_id             BIGINT NOT NULL,
    forum_channel_id     BIGINT NOT NULL,
    team_role_id         BIGINT,
    intern_role_id       BIGINT,
    grad_role_id         BIGINT,
    professional_role_id BIGINT,
    -- Weekly recap destinations, one per audience. The recap is the only thing
    -- that pings; individual job posts do not mention a role.
    intern_recap_channel_id BIGINT,
    grad_recap_channel_id   BIGINT,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS job_posts (
    -- Identity
    job_id              VARCHAR(24) NOT NULL,
    guild_id            BIGINT      NOT NULL,

    -- Forum post metadata
    forum_post_id       BIGINT      NOT NULL,
    forum_channel_id    BIGINT      NOT NULL,
    posted_at           TIMESTAMPTZ NOT NULL,
    awaiting_deletion   BOOLEAN     NOT NULL DEFAULT FALSE,
    deletion_message_id BIGINT,

    -- Job data (denormalized from MongoDB)
    title               TEXT        NOT NULL,
    job_type            TEXT,
    application_url     TEXT,
    one_liner           TEXT,
    description         TEXT,
    close_date          TIMESTAMPTZ,
    industry_field      TEXT,
    is_sponsored        BOOLEAN     NOT NULL DEFAULT FALSE,
    outdated            BOOLEAN     NOT NULL DEFAULT FALSE,
    source              TEXT,
    version             TEXT,
    wfh_status          TEXT,
    days_lived          INTEGER,
    fingerprint         TEXT,
    locations           JSON        NOT NULL DEFAULT '[]',
    source_urls         JSON        NOT NULL DEFAULT '[]',
    study_fields        JSON        NOT NULL DEFAULT '[]',
    working_rights      JSON        NOT NULL DEFAULT '[]',
    company_name        TEXT        NOT NULL DEFAULT '',
    company_website     TEXT,
    company_logo        TEXT,
    job_created_at      TIMESTAMPTZ,
    job_updated_at      TIMESTAMPTZ,

    PRIMARY KEY (job_id, guild_id)
);
