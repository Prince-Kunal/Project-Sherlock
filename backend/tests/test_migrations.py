from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base

# PLAN.md §5
EXPECTED_TABLES = {
    "users",
    "allowed_emails",
    "user_preferences",
    "master_resumes",
    "companies",
    "prospect_targets",
    "company_matches",
    "user_company_blocks",
    "jobs",
    "job_matches",
    "contacts",
    "outreach",
    "outreach_events",
    "suppression_list",
    "oauth_tokens",
    "user_llm_keys",
    "usage_ledger",
}


async def test_all_plan_tables_exist(session: AsyncSession) -> None:
    rows = await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    tables = {r[0] for r in rows}
    assert tables >= EXPECTED_TABLES
    assert set(Base.metadata.tables) == EXPECTED_TABLES


async def test_vector_extension_enabled(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    assert result.scalar_one() == 1


async def test_every_table_has_id_and_timestamps(session: AsyncSession) -> None:
    for table in Base.metadata.sorted_tables:
        assert {"id", "created_at", "updated_at"} <= set(table.c.keys()), table.name


async def test_user_owned_tables_index_user_id() -> None:
    for table in Base.metadata.sorted_tables:
        if "user_id" in table.c:
            column = table.c.user_id
            indexed = (
                column.index or column.unique or any(next(iter(ix.columns)) is column for ix in table.indexes)
            )
            assert indexed, f"{table.name}.user_id is not indexed"
