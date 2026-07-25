-- Reference DDL for guild_configs and job_posts tables.
-- SQLModel generates these automatically at startup via SQLModel.metadata.create_all.

CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id        BIGINT      NOT NULL,
    forum_channel_id BIGINT     NOT NULL,
    team_role_id    BIGINT,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS job_posts (
    job_id              VARCHAR(24) NOT NULL,
    guild_id            BIGINT      NOT NULL,
    forum_post_id       BIGINT      NOT NULL,
    forum_channel_id    BIGINT      NOT NULL,
    posted_at           TIMESTAMP   NOT NULL,
    awaiting_deletion   BOOLEAN     NOT NULL DEFAULT FALSE,
    deletion_message_id BIGINT,
    PRIMARY KEY (job_id, guild_id)
);
