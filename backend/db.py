import os

import asyncpg
import psycopg
from psycopg.rows import dict_row

from rules import DEFAULT_LIMIT_C, judge_temp

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54397/coldchain"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lines (
    id text PRIMARY KEY,
    name text NOT NULL,
    limit_c double precision NOT NULL,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS line_limit_history (
    id serial PRIMARY KEY,
    line_id text NOT NULL REFERENCES lines (id),
    old_limit_c double precision,
    new_limit_c double precision NOT NULL,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_line_limit_history_line
    ON line_limit_history (line_id, id DESC);

CREATE TABLE IF NOT EXISTS probe_readings (
    id serial PRIMARY KEY,
    probe_id text NOT NULL,
    line_id text REFERENCES lines (id),
    temp_c double precision NOT NULL,
    limit_c double precision,
    verdict text,
    reason text,
    status text NOT NULL DEFAULT 'pending',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS line_id text REFERENCES lines (id);
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS limit_c double precision;
CREATE INDEX IF NOT EXISTS idx_probe_readings_status ON probe_readings (status, id);
"""

# 种子厢线：不同厢线可配不同合格摄氏上限，默认均为 8℃。
SEED_LINES = [
    ("甲", "厢线甲", DEFAULT_LIMIT_C),
    ("乙", "厢线乙", DEFAULT_LIMIT_C),
]

SEED_READINGS = [
    ("探头A01", "甲", 4.2),
    ("探头B02", "乙", 12.5),
]


def connect_sync():
    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)
    conn.commit()


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DSN, min_size=1, max_size=5)


async def ensure_schema_async(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


async def seed_lines_async(conn) -> None:
    for line_id, name, limit_c in SEED_LINES:
        await conn.execute(
            """
            INSERT INTO lines (id, name, limit_c, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (id) DO NOTHING
            """,
            line_id,
            name,
            limit_c,
        )


def seed_lines_sync(conn) -> None:
    for line_id, name, limit_c in SEED_LINES:
        conn.execute(
            """
            INSERT INTO lines (id, name, limit_c, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (id) DO NOTHING
            """,
            (line_id, name, limit_c),
        )
    conn.commit()


async def seed_if_empty(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await seed_lines_async(conn)
        n = await conn.fetchval("SELECT COUNT(*) FROM probe_readings")
        if n and n > 0:
            return
        for probe_id, line_id, temp_c in SEED_READINGS:
            limit_c = await conn.fetchval(
                "SELECT limit_c FROM lines WHERE id = $1", line_id
            )
            verdict, reason = judge_temp(temp_c, limit_c)
            await conn.execute(
                """
                INSERT INTO probe_readings
                    (probe_id, line_id, temp_c, limit_c, verdict, reason,
                     status, created_by, processed_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'done', 'logger', now())
                """,
                probe_id,
                line_id,
                temp_c,
                limit_c,
                verdict,
                reason,
            )


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM probe_readings").fetchone()
    if row["n"] > 0:
        return
    for probe_id, line_id, temp_c in SEED_READINGS:
        limit_row = conn.execute(
            "SELECT limit_c FROM lines WHERE id = %s", (line_id,)
        ).fetchone()
        limit_c = limit_row["limit_c"]
        verdict, reason = judge_temp(temp_c, limit_c)
        conn.execute(
            """
            INSERT INTO probe_readings
                (probe_id, line_id, temp_c, limit_c, verdict, reason,
                 status, created_by, processed_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'done', 'logger', now())
            """,
            (probe_id, line_id, temp_c, limit_c, verdict, reason),
        )
    conn.commit()
