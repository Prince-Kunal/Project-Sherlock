"""Warm-path hints (PLAN.md Phase 10): people the user already knows at a company.

The user uploads a list of their own connections: LinkedIn's export (Settings → Data privacy → Get a
copy of your data → Connections, a `Connections.csv` with a few note lines before the header) or any
CSV with a name and company column, optionally a school. Sherlock never scrapes LinkedIn and never
contacts these people; it only matches their company against the user's matches and drafts, and
marks those who went to the same college as the user (from the master resume's education).

Connections stay in `user_connections` (deleted with the user, invariant 5), are never sent to the
LLM, and an upload replaces the previous list.
"""

import csv
import io
import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, UserConnection
from app.schemas.connections import KnownPersonOut, WarmPathOut
from app.schemas.resume import MasterResume
from app.services.resume import store

MAX_ROWS = 20_000
MAX_NAMES_SHOWN = 5

_COLUMNS = {
    "first": ("first name", "firstname", "given name"),
    "last": ("last name", "lastname", "surname", "family name"),
    "name": ("name", "full name", "fullname", "connection"),
    "company": ("company", "current company", "organization", "organisation", "employer", "company name"),
    "position": ("position", "title", "job title", "role", "designation"),
    "school": ("school", "college", "university", "education", "alma mater"),
    "url": ("url", "profile url", "linkedin", "linkedin url", "profile"),
}
# Trailing words that don't identify a company ("Razorpay Software Private Limited" → "razorpay").
_COMPANY_NOISE = {
    "pvt", "private", "ltd", "limited", "inc", "incorporated", "llc", "llp", "corp", "corporation",
    "co", "company", "gmbh", "plc", "pte", "sa", "ag", "bv", "india", "software", "technologies",
    "technology", "tech", "solutions", "services", "systems", "labs", "group", "global", "hq",
}  # fmt: skip
_SCHOOL_NOISE = {"the", "of", "and", "at"}


class ConnectionsFileError(ValueError):
    pass


def _ascii_words(value: str) -> list[str]:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).split()


def company_key(value: str | None) -> str:
    words = _ascii_words(value or "")
    while len(words) > 1 and words[-1] in _COMPANY_NOISE:
        words.pop()
    return " ".join(words)


def school_key(value: str | None) -> str:
    return " ".join(w for w in _ascii_words(value or "") if w not in _SCHOOL_NOISE)


def domain_key(domain: str | None) -> str:
    """ "razorpay.com" → "razorpay", so a connection at "Razorpay" matches a company known by domain."""
    if not domain:
        return ""
    host = domain.lower().removeprefix("www.")
    return company_key(host.split(".")[0])


def name_key(value: str | None) -> str:
    return " ".join(_ascii_words(value or ""))


@dataclass
class ParsedConnection:
    full_name: str
    company: str = ""
    position: str = ""
    school: str = ""
    profile_url: str | None = None


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ConnectionsFileError("couldn't read the file as text (save it as CSV, UTF-8)")


def _header_map(row: list[str]) -> dict[str, int]:
    cells = [c.strip().lower() for c in row]
    found = {}
    for field_name, aliases in _COLUMNS.items():
        for i, cell in enumerate(cells):
            if cell in aliases:
                found[field_name] = i
                break
    return found


def parse_connections_csv(data: bytes) -> list[ParsedConnection]:
    """Rows with a name; LinkedIn's note lines before the header are skipped. Raises
    ConnectionsFileError when no header with a name and a company column is found."""
    rows = list(csv.reader(io.StringIO(_decode(data))))
    columns: dict[str, int] = {}
    start = 0
    for i, row in enumerate(rows[:20]):  # LinkedIn puts a few "Notes:" lines first
        columns = _header_map(row)
        if "company" in columns and ("name" in columns or "first" in columns):
            start = i + 1
            break
    else:
        raise ConnectionsFileError("no header row with a name and a company column was found")

    def cell(row: list[str], key: str) -> str:
        index = columns.get(key)
        return row[index].strip() if index is not None and index < len(row) else ""

    people = []
    for row in rows[start : start + MAX_ROWS]:
        name = cell(row, "name") or " ".join(p for p in (cell(row, "first"), cell(row, "last")) if p)
        if not name:
            continue
        url = cell(row, "url")
        people.append(
            ParsedConnection(
                full_name=name[:300],
                company=cell(row, "company")[:300],
                position=cell(row, "position")[:300],
                school=cell(row, "school")[:300],
                profile_url=url if url.startswith("http") else None,
            )
        )
    return people


async def replace_connections(
    session: AsyncSession, user_id: uuid.UUID, people: list[ParsedConnection]
) -> int:
    """Swap the user's list for `people`. Caller commits."""
    await session.execute(delete(UserConnection).where(UserConnection.user_id == user_id))
    session.add_all(
        UserConnection(
            user_id=user_id,
            full_name=p.full_name,
            company=p.company,
            company_key=company_key(p.company),
            position=p.position,
            school=p.school,
            school_key=school_key(p.school),
            profile_url=p.profile_url,
        )
        for p in people
    )
    return len(people)


async def user_school_keys(session: AsyncSession, user_id: uuid.UUID) -> set[str]:
    row = await store.get_current(session, user_id)
    if row is None:
        return set()
    resume = MasterResume.model_validate(row.data)
    return {k for k in (school_key(e.institution) for e in resume.education) if k}


def same_school(connection_school: str, mine: set[str]) -> bool:
    if not connection_school:
        return False
    return any(connection_school == s or connection_school in s or s in connection_school for s in mine)


@dataclass
class KnownPerson:
    name: str
    position: str
    alumni: bool  # went to the user's college
    profile_url: str | None


@dataclass
class WarmPath:
    count: int = 0
    alumni: int = 0
    people: list[KnownPerson] = field(default_factory=list)  # alumni first, at most MAX_NAMES_SHOWN


async def warm_paths(
    session: AsyncSession, user_id: uuid.UUID, companies: list[Company]
) -> dict[uuid.UUID, WarmPath]:
    """For each company, the user's connections who work there (matched by name, or by the company's
    domain stem). Companies with nobody are left out."""
    keys: dict[str, set[uuid.UUID]] = defaultdict(set)
    for company in companies:
        for key in {company_key(company.name), domain_key(company.domain)} - {""}:
            keys[key].add(company.id)
    if not keys:
        return {}
    rows = (
        await session.scalars(
            select(UserConnection).where(
                UserConnection.user_id == user_id, UserConnection.company_key.in_(list(keys))
            )
        )
    ).all()
    if not rows:
        return {}
    schools = await user_school_keys(session, user_id)
    found: dict[uuid.UUID, list[KnownPerson]] = defaultdict(list)
    for row in rows:
        person = KnownPerson(
            name=row.full_name,
            position=row.position,
            alumni=same_school(row.school_key, schools),
            profile_url=row.profile_url,
        )
        for company_id in keys[row.company_key]:
            found[company_id].append(person)
    paths = {}
    for company_id, people in found.items():
        people.sort(key=lambda p: (not p.alumni, p.name))
        paths[company_id] = WarmPath(
            count=len(people), alumni=sum(p.alumni for p in people), people=people[:MAX_NAMES_SHOWN]
        )
    return paths


def knows_contact(path: WarmPath | None, contact_name: str | None) -> bool:
    """Whether the person a draft is addressed to is one of the user's own connections."""
    key = name_key(contact_name)
    return bool(path and key and any(name_key(p.name) == key for p in path.people))


async def connections_summary(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int, int]:
    """(people, companies with someone, alumni of the user's college)."""
    total, companies = (
        await session.execute(
            select(func.count(), func.count(func.distinct(UserConnection.company_key))).where(
                UserConnection.user_id == user_id
            )
        )
    ).one()
    schools = await user_school_keys(session, user_id)
    alumni = 0
    if schools:
        keys = await session.scalars(
            select(UserConnection.school_key).where(
                UserConnection.user_id == user_id, UserConnection.school_key != ""
            )
        )
        alumni = sum(1 for k in keys if same_school(k, schools))
    return int(total), int(companies), alumni


def warm_path_out(path: WarmPath | None) -> WarmPathOut | None:
    if path is None:
        return None
    return WarmPathOut(
        count=path.count,
        alumni=path.alumni,
        people=[KnownPersonOut(**p.__dict__) for p in path.people],
    )
