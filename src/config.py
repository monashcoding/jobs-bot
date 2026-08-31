from __future__ import annotations

# How often the deadline checker runs, in minutes. Edit to change frequency.
DEADLINE_CHECK_INTERVAL_MINUTES: int = 60

# Weekly recap schedule, in UTC. Monday 22:00 UTC is Tuesday 8am/9am in Sydney
# depending on daylight saving, which puts it in front of people at the start of
# the week rather than over a weekend.
RECAP_DAY: int = 0  # Monday, matching datetime.weekday()
RECAP_HOUR_UTC: int = 22
