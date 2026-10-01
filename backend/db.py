import os

import asyncpg
import psycopg
from psycopg.rows import dict_row

from rules import judge_temp

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54397/coldchain"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lines (
    id text PRIMARY KEY,
    name text NOT NULL,
    limit_c double precision NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS line_limit_changes (
    id serial PRIMARY KEY,
    line_id text NOT NULL REFERENCES lines (id),
    old_limit_c double precision,
    new_limit_c double precision NOT NULL,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_line_limit_changes_line
    ON line_limit_changes (line_id, id DESC);

CREATE TABLE IF NOT EXISTS probe_readings (
    id serial PRIMARY KEY,
    line_id text REFERENCES lines (id),
    probe_id text NOT NULL,
    temp_c double precision NOT NULL,
    limit_c double precision,
    verdict text,
    reason text,
    status text NOT NULL DEFAULT 'pending',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_probe_readings_status ON probe_readings (status, id);
"""

# 既有库补列（开发环境幂等升级；列已存在则跳过）。
MIGRATIONS_SQL = """
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS line_id text REFERENCES lines (id);
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS limit_c double precision;
"""

# 厢线代码与展示名：代码稳定（外键/提交用），名字可中文。
SEED_LINES = [
    ("jia", "厢线甲", 8.0),
    ("yi", "厢线乙", 8.0),
]


def connect_sync():
    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)
    conn.execute(MIGRATIONS_SQL)


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DSN, min_size=1, max_size=5)


async def ensure_schema_async(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(MIGRATIONS_SQL)


async def seed_if_empty(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM lines")
        if not n:
            for line_id, name, limit_c in SEED_LINES:
                await conn.execute(
                    """
                    INSERT INTO lines (id, name, limit_c, updated_by, updated_at)
                    VALUES ($1, $2, $3, 'logger', now())
                    """,
                    line_id,
                    name,
                    limit_c,
                )
        n = await conn.fetchval("SELECT COUNT(*) FROM probe_readings")
        if n and n > 0:
            return
        samples = [
            ("jia", "探头A01", 4.2),
            ("yi", "探头B02", 12.5),
        ]
        for line_id, probe_id, temp_c in samples:
            limit_c = await conn.fetchval(
                "SELECT limit_c FROM lines WHERE id = $1", line_id
            )
            verdict, reason = judge_temp(temp_c, limit_c)
            await conn.execute(
                """
                INSERT INTO probe_readings
                    (line_id, probe_id, temp_c, limit_c, verdict, reason,
                     status, created_by, processed_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'done', 'logger', now())
                """,
                line_id,
                probe_id,
                temp_c,
                limit_c,
                verdict,
                reason,
            )


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM lines").fetchone()
    if row["n"] == 0:
        for line_id, name, limit_c in SEED_LINES:
            conn.execute(
                """
                INSERT INTO lines (id, name, limit_c, updated_by, updated_at)
                VALUES (%s, %s, %s, 'logger', now())
                """,
                (line_id, name, limit_c),
            )
    row = conn.execute("SELECT COUNT(*) AS n FROM probe_readings").fetchone()
    if row["n"] > 0:
        conn.commit()
        return
    for line_id, probe_id, temp_c in [
        ("jia", "探头A01", 4.2),
        ("yi", "探头B02", 12.5),
    ]:
        line = conn.execute(
            "SELECT limit_c FROM lines WHERE id = %s", (line_id,)
        ).fetchone()
        verdict, reason = judge_temp(temp_c, line["limit_c"])
        conn.execute(
            """
            INSERT INTO probe_readings
                (line_id, probe_id, temp_c, limit_c, verdict, reason,
                 status, created_by, processed_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'done', 'logger', now())
            """,
            (line_id, probe_id, temp_c, line["limit_c"], verdict, reason),
        )
    conn.commit()
