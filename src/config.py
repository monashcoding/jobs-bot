from __future__ import annotations

# How often the deadline checker runs, in minutes. Edit to change frequency.
DEADLINE_CHECK_INTERVAL_MINUTES: int = 60

# Weekly recap schedule, in local time for RECAP_TIMEZONE.
#
# The zone is named explicitly rather than the hour being pinned to UTC: the
# container runs in UTC, and Sydney moves between UTC+10 and UTC+11, so a fixed
# UTC hour would drift an hour twice a year and eventually stop being "Friday
# night" at all.
RECAP_TIMEZONE: str = "Australia/Sydney"
RECAP_DAY: int = 4  # Friday, matching datetime.weekday()
RECAP_HOUR: int = 19  # 7pm local
