"""后台工人：用 SKIP LOCKED 认领 pending 读数。

领单（置为 processing）的同一事务里，把该厢线“现行上限”抄进读数的 limit_c
作为快照；判定合格/超温时只认这份快照。因此领单后再改档，既不影响处理中的单，
也不影响已完成的单——只有领单之后新提交/新认领的单才吃新上限。
"""

import os
import time

from db import connect_sync, ensure_schema_sync, seed_if_empty_sync, seed_lines_sync
from rules import judge_temp

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))


def claim_one(conn):
    with conn.transaction():
        row = conn.execute(
            """
            SELECT id, probe_id, line_id, temp_c
            FROM probe_readings
            WHERE status = 'pending'
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        # 锁住厢线行，与改档事务串行，确保抄到的是领单瞬间的现行上限。
        line = conn.execute(
            "SELECT limit_c FROM lines WHERE id = %s FOR UPDATE",
            (row["line_id"],),
        ).fetchone()
        limit_c = line["limit_c"] if line else None
        conn.execute(
            """
            UPDATE probe_readings
            SET status = 'processing', limit_c = %s
            WHERE id = %s
            """,
            (limit_c, row["id"]),
        )
        row["limit_c"] = limit_c
        return row


def finish(conn, reading_id: int, temp_c: float, limit_c: float | None) -> None:
    if limit_c is None:
        limit_c = 8.0
    verdict, reason = judge_temp(float(temp_c), float(limit_c))
    conn.execute(
        """
        UPDATE probe_readings
        SET status = 'done', verdict = %s, reason = %s, processed_at = now()
        WHERE id = %s
        """,
        (verdict, reason, reading_id),
    )
    conn.commit()


def run_once(conn) -> bool:
    row = claim_one(conn)
    if not row:
        return False
    try:
        finish(conn, row["id"], float(row["temp_c"]), row.get("limit_c"))
    except Exception:
        conn.execute(
            "UPDATE probe_readings SET status = 'pending' WHERE id = %s",
            (row["id"],),
        )
        conn.commit()
        raise
    return True


def main() -> None:
    with connect_sync() as conn:
        ensure_schema_sync(conn)
        seed_lines_sync(conn)
        seed_if_empty_sync(conn)
        conn.commit()

    while True:
        try:
            with connect_sync() as conn:
                processed = run_once(conn)
        except Exception as exc:
            print(f"worker error: {exc}", flush=True)
            processed = False
        if not processed:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
