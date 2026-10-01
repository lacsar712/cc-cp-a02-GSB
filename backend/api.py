import json
import math
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import jwt
from aiohttp import web
from passlib.context import CryptContext

from db import create_pool, ensure_schema_async, seed_if_empty, seed_lines_async

SECRET = os.environ.get("JWT_SECRET", "coldchain-probe-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

USERS = {
    "logger": {"role": "writer", "password_hash": pwd.hash("log123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


def _auth_header(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _decode_user(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def require_user(request: web.Request) -> dict:
    user = _decode_user(_auth_header(request))
    if not user:
        raise web.HTTPUnauthorized(text=json.dumps({"detail": "未登录"}, ensure_ascii=False), content_type="application/json")
    return user


def require_writer(request: web.Request, action: str = "提交读数") -> dict:
    user = require_user(request)
    if user["role"] != "writer":
        raise web.HTTPForbidden(
            text=json.dumps({"detail": f"仅记录员可{action}"}, ensure_ascii=False),
            content_type="application/json",
        )
    return user


def _json_error(detail: str, status: type[web.HTTPException]) -> web.HTTPException:
    return status(
        text=json.dumps({"detail": detail}, ensure_ascii=False),
        content_type="application/json",
    )


def _reading_out(r: asyncpg.Record) -> dict:
    return {
        "id": r["id"],
        "probe_id": r["probe_id"],
        "line_id": r["line_id"],
        "line_name": r["line_name"],
        "temp_c": r["temp_c"],
        "limit_c": r["limit_c"],
        "verdict": r["verdict"],
        "reason": r["reason"],
        "status": r["status"],
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "processed_at": r["processed_at"].isoformat() if r["processed_at"] else None,
    }


READING_COLS = """
    SELECT r.id, r.probe_id, r.line_id, l.name AS line_name,
           r.temp_c, r.limit_c, r.verdict, r.reason, r.status,
           r.created_by, r.created_at, r.processed_at
    FROM probe_readings r
    LEFT JOIN lines l ON l.id = r.line_id
"""


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "coldchain-probe-desk"})


async def login(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise web.HTTPUnauthorized(
            text=json.dumps({"detail": "用户名或密码错误"}, ensure_ascii=False),
            content_type="application/json",
        )
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp},
        SECRET,
        algorithm="HS256",
    )
    return web.json_response(
        {"access_token": token, "username": username, "role": user["role"]}
    )


async def list_readings(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(READING_COLS + " ORDER BY r.id DESC")
    return web.json_response([_reading_out(r) for r in rows])


async def create_reading(request: web.Request) -> web.Response:
    user = require_writer(request)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    probe_id = str(body.get("probe_id", "")).strip()
    if not probe_id:
        raise _json_error("探头编号不能为空", web.HTTPBadRequest)
    line_id = str(body.get("line_id", "")).strip()
    if not line_id:
        raise _json_error("请选择厢线", web.HTTPBadRequest)
    try:
        temp_c = float(body.get("temp_c"))
    except (TypeError, ValueError) as exc:
        raise _json_error("温度必须是数字", web.HTTPBadRequest) from exc
    if not math.isfinite(temp_c):
        raise _json_error("温度必须是数字", web.HTTPBadRequest)

    pool: asyncpg.Pool = request.app["pool"]
    # limit_c 留空：领单（processing）时由工人抄录该厢线现行上限作为快照。
    row = await pool.fetchrow(
        """
        WITH ins AS (
            INSERT INTO probe_readings (probe_id, line_id, temp_c, status, created_by, created_at)
            SELECT $1, l.id, $2, 'pending', $3, now()
            FROM lines l WHERE l.id = $4
            RETURNING id, probe_id, line_id, temp_c, limit_c, verdict, reason,
                      status, created_by, created_at, processed_at
        )
        SELECT r.id, r.probe_id, r.line_id, l.name AS line_name,
               r.temp_c, r.limit_c, r.verdict, r.reason, r.status,
               r.created_by, r.created_at, r.processed_at
        FROM ins r
        LEFT JOIN lines l ON l.id = r.line_id
        """,
        probe_id,
        temp_c,
        user["username"],
        line_id,
    )
    if not row:
        raise _json_error("厢线不存在", web.HTTPBadRequest)
    out = _reading_out(row)
    out["message"] = "已入队，后台工人领单时抄录该厢线现行上限并判定"
    return web.json_response(out, status=201)


async def list_lines(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(
        """
        SELECT id, name, limit_c, updated_by, updated_at
        FROM lines
        ORDER BY id
        """
    )
    return web.json_response(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "limit_c": r["limit_c"],
                "updated_by": r["updated_by"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]
    )


async def list_line_history(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(
        """
        SELECT h.id, h.line_id, l.name AS line_name,
               h.old_limit_c, h.new_limit_c, h.changed_by, h.changed_at
        FROM line_limit_history h
        LEFT JOIN lines l ON l.id = h.line_id
        ORDER BY h.id DESC
        """
    )
    return web.json_response(
        [
            {
                "id": r["id"],
                "line_id": r["line_id"],
                "line_name": r["line_name"],
                "old_limit_c": r["old_limit_c"],
                "new_limit_c": r["new_limit_c"],
                "changed_by": r["changed_by"],
                "changed_at": r["changed_at"].isoformat() if r["changed_at"] else None,
            }
            for r in rows
        ]
    )


async def update_line_limit(request: web.Request) -> web.Response:
    user = require_writer(request, action="修改分线上限")
    line_id = request.match_info["line_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    try:
        new_limit = float(body.get("limit_c"))
    except (TypeError, ValueError) as exc:
        raise _json_error("上限必须是数字", web.HTTPBadRequest) from exc
    if not math.isfinite(new_limit):
        raise _json_error("上限必须是数字", web.HTTPBadRequest)

    pool: asyncpg.Pool = request.app["pool"]
    async with pool.acquire() as conn:
        async with conn.transaction():
            line = await conn.fetchrow(
                "SELECT id, name, limit_c FROM lines WHERE id = $1 FOR UPDATE",
                line_id,
            )
            if not line:
                raise _json_error("厢线不存在", web.HTTPNotFound)
            old_limit = line["limit_c"]
            if old_limit == new_limit:
                raise _json_error("新上限与现行上限相同，无需改档", web.HTTPBadRequest)
            await conn.execute(
                "UPDATE lines SET limit_c = $1, updated_by = $2, updated_at = now() WHERE id = $3",
                new_limit,
                user["username"],
                line_id,
            )
            await conn.execute(
                """
                INSERT INTO line_limit_history
                    (line_id, old_limit_c, new_limit_c, changed_by, changed_at)
                VALUES ($1, $2, $3, $4, now())
                """,
                line_id,
                old_limit,
                new_limit,
                user["username"],
            )
    updated = await pool.fetchrow(
        "SELECT id, name, limit_c, updated_by, updated_at FROM lines WHERE id = $1",
        line_id,
    )
    return web.json_response(
        {
            "id": updated["id"],
            "name": updated["name"],
            "limit_c": updated["limit_c"],
            "updated_by": updated["updated_by"],
            "updated_at": updated["updated_at"].isoformat() if updated["updated_at"] else None,
            "message": f"{updated['name']}上限已由 {old_limit:g}℃ 改为 {new_limit:g}℃",
        }
    )


async def on_startup(app: web.Application) -> None:
    pool = await create_pool()
    app["pool"] = pool
    await ensure_schema_async(pool)
    async with pool.acquire() as conn:
        await seed_lines_async(conn)
    await seed_if_empty(pool)


async def on_cleanup(app: web.Application) -> None:
    pool: asyncpg.Pool = app.get("pool")
    if pool:
        await pool.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/api/readings", list_readings)
    app.router.add_post("/api/readings", create_reading)
    app.router.add_get("/api/lines", list_lines)
    app.router.add_get("/api/lines/history", list_line_history)
    app.router.add_put("/api/lines/{line_id}", update_line_limit)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
