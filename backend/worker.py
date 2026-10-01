"""后台工人：用 SKIP LOCKED 认领 pending 读数并写入合格/超温结论。

领单瞬间把该厢线的现行合格上限抄到读数行（limit_c 快照）；
判定一律按快照走，处理中的单不受后续改档影响。
"""

import os
import time

from db import connect_sync, ensure_schema_sync, seed_if_empty_sync
from rules import judge_temp

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))


def claim_one(conn):
    with conn.transaction():
        row = conn.execute(
            """
            SELECT r.id, r.probe_id, r.temp_c, l.limit_c
            FROM probe_readings r
            JOIN lines l ON l.id = r.line_id
            WHERE r.status = 'pending'
            ORDER BY r.id
            FOR UPDATE OF r SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        # 抄下领单当时的该厢线上限，后续改档不影响本单。
        conn.execute(
            "UPDATE probe_readings SET status = 'processing', limit_c = %s WHERE id = %s",
            (row["limit_c"], row["id"]),
        )
        return row


def finish(conn, reading_id: int, temp_c: float, limit_c: float) -> None:
    verdict, reason = judge_temp(temp_c, limit_c)
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
        finish(conn, row["id"], float(row["temp_c"]), float(row["limit_c"]))
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
