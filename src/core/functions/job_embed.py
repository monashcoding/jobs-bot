from __future__ import annotations

import re

import discord

from src.backend.mongo.collections.col_jobs import JobDocument

# Map job type -> embed colour
_TYPE_COLOURS: dict[str, discord.Colour] = {
    "GRADUATE": discord.Colour.blue(),
    "INTERNSHIP": discord.Colour.green(),
    "PART_TIME": discord.Colour.orange(),
    "FULL_TIME": discord.Colour.blurple(),
    "CONTRACT": discord.Colour.gold(),
    "CASUAL": discord.Colour.teal(),
}

_WORKING_RIGHTS_LABELS: dict[str, str] = {
    "AUS_CITIZEN_PR": "AU Citizen/PR",
    "AUS_STUDENT_VISA": "AU Student Visa",
    "AUS_WORKING_VISA": "AU Working Visa",
    "NZ_CITIZEN_PR": "NZ Citizen/PR",
    "NZ_STUDENT_VISA": "NZ Student Visa",
    "NZ_WORKING_VISA": "NZ Working Visa",
    "ANY": "Any",
}

_INDUSTRY_LABELS: dict[str, str] = {
    "SOFTWARE_ENGINEERING": "Software Engineering",
    "DATA_SCIENCE": "Data Science",
    "CYBERSECURITY": "Cybersecurity",
    "IT_GENERAL": "IT (General)",
    "FINANCE": "Finance",
    "CONSULTING": "Consulting",
    "ENGINEERING": "Engineering",
    "DESIGN": "Design",
    "MARKETING": "Marketing",
    "OPERATIONS": "Operations",
    "HR": "Human Resources",
    "LEGAL": "Legal",
    "HEALTHCARE": "Healthcare",
    "EDUCATION": "Education",
    "RESEARCH": "Research",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _fmt_list(values: list[str], label_map: dict[str, str] | None = None) -> str:
    if not values:
        return "N/A"
    if label_map:
        return ", ".join(label_map.get(v, v) for v in values)
    return ", ".join(values)


def build_job_embed(job: JobDocument) -> discord.Embed:
    """Build a discord.Embed from a JobDocument."""

    title = f"{job.title} | {job.company.name}"[:256]
    colour = _TYPE_COLOURS.get(job.type or "", discord.Colour.default())

    description_parts: list[str] = []
    if job.one_liner:
        description_parts.append(f"*{job.one_liner}*")
    if job.description:
        description_parts.append(_strip_html(job.description))

    description = "\n\n".join(description_parts)[:4000] if description_parts else ""

    embed = discord.Embed(
        title=title,
        url=job.application_url,
        description=description or None,
        colour=colour,
    )

    if job.company.logo:
        embed.set_thumbnail(url=job.company.logo)

    if job.type:
        embed.add_field(
            name="Type", value=job.type.replace("_", " ").title(), inline=True
        )

    if job.locations:
        embed.add_field(name="Locations", value=_fmt_list(job.locations), inline=True)

    if job.industry_field:
        embed.add_field(
            name="Industry",
            value=_INDUSTRY_LABELS.get(job.industry_field, job.industry_field),
            inline=True,
        )

    if job.study_fields:
        embed.add_field(
            name="Study Fields", value=_fmt_list(job.study_fields), inline=False
        )

    if job.working_rights:
        embed.add_field(
            name="Working Rights",
            value=_fmt_list(job.working_rights, _WORKING_RIGHTS_LABELS),
            inline=False,
        )

    if job.close_date:
        embed.add_field(
            name="Close Date",
            value=discord.utils.format_dt(job.close_date, style="D"),
            inline=True,
        )

    if job.wfh_status:
        embed.add_field(
            name="WFH Status",
            value=job.wfh_status.replace("_", " ").title(),
            inline=True,
        )

    embed.add_field(
        name="Sponsored",
        value="Yes" if job.is_sponsored else "No",
        inline=True,
    )

    if job.source:
        embed.set_footer(text=job.source)

    return embed
