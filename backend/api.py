import json
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import jwt
from aiohttp import web
from passlib.context import CryptContext

from db import create_pool, ensure_schema_async, seed_if_empty

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


def require_writer(request: web.Request) -> dict:
    user = require_user(request)
    if user["role"] != "writer":
        raise web.HTTPForbidden(
            text=json.dumps({"detail": "仅记录员可执行该操作"}, ensure_ascii=False),
            content_type="application/json",
        )
    return user


def _error(detail: str, status: int) -> web.HTTPException:
    cls = {
        400: web.HTTPBadRequest,
        403: web.HTTPForbidden,
        404: web.HTTPNotFound,
        409: web.HTTPConflict,
    }[status]
    return cls(
        text=json.dumps({"detail": detail}, ensure_ascii=False),
        content_type="application/json",
    )


def _parse_float(value, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise _error(f"{field}必须是数字", 400) from exc
    if out != out or out in (float("inf"), float("-inf")):
        raise _error(f"{field}必须是有限数字", 400)
    return out


def _line_json(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "limit_c": r["limit_c"],
        "updated_by": r["updated_by"],
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _reading_json(r) -> dict:
    return {
        "id": r["id"],
        "line_id": r["line_id"],
        "line_name": r["line_name"],
        "probe_id": r["probe_id"],
        "temp_c": r["temp_c"],
        "limit_c": r["limit_c"],
        "verdict": r["verdict"],
        "reason": r["reason"],
        "status": r["status"],
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "processed_at": r["processed_at"].isoformat() if r["processed_at"] else None,
    }


READING_SELECT = """
    SELECT r.id, r.line_id, l.name AS line_name, r.probe_id, r.temp_c,
           r.limit_c, r.verdict, r.reason, r.status, r.created_by,
           r.created_at, r.processed_at
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


async def list_lines(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch("SELECT * FROM lines ORDER BY id")
    return web.json_response([_line_json(r) for r in rows])


async def create_line(request: web.Request) -> web.Response:
    user = require_writer(request)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    line_id = str(body.get("id", "")).strip()
    name = str(body.get("name", "")).strip()
    if not line_id or not name:
        raise _error("厢线代码与名称不能为空", 400)
    if len(line_id) > 32 or any(ch.isspace() for ch in line_id):
        raise _error("厢线代码需为 32 字以内且不含空白", 400)
    limit_c = _parse_float(body.get("limit_c"), "合格上限")

    pool: asyncpg.Pool = request.app["pool"]
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO lines (id, name, limit_c, updated_by, updated_at)
                    VALUES ($1, $2, $3, $4, now())
                    RETURNING *
                    """,
                    line_id,
                    name,
                    limit_c,
                    user["username"],
                )
            except asyncpg.UniqueViolationError as exc:
                raise _error("该厢线代码已存在", 409) from exc
            await conn.execute(
                """
                INSERT INTO line_limit_changes
                    (line_id, old_limit_c, new_limit_c, changed_by, changed_at)
                VALUES ($1, NULL, $2, $3, now())
                """,
                line_id,
                limit_c,
                user["username"],
            )
    return web.json_response(_line_json(row), status=201)


async def update_line_limit(request: web.Request) -> web.Response:
    user = require_writer(request)
    line_id = request.match_info["line_id"]
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    new_limit = _parse_float(body.get("limit_c"), "合格上限")

    pool: asyncpg.Pool = request.app["pool"]
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM lines WHERE id = $1 FOR UPDATE", line_id
            )
            if not row:
                raise _error("厢线不存在", 404)
            old_limit = float(row["limit_c"])
            if old_limit == new_limit:
                raise _error("新上限与现行上限相同，无需改档", 400)
            await conn.execute(
                """
                INSERT INTO line_limit_changes
                    (line_id, old_limit_c, new_limit_c, changed_by, changed_at)
                VALUES ($1, $2, $3, $4, now())
                """,
                line_id,
                old_limit,
                new_limit,
                user["username"],
            )
            row = await conn.fetchrow(
                """
                UPDATE lines
                SET limit_c = $2, updated_by = $3, updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                line_id,
                new_limit,
                user["username"],
            )
    return web.json_response(_line_json(row))


async def list_line_changes(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    line_id = request.query.get("line_id")
    if line_id:
        rows = await pool.fetch(
            """
            SELECT c.id, c.line_id, l.name AS line_name, c.old_limit_c,
                   c.new_limit_c, c.changed_by, c.changed_at
            FROM line_limit_changes c
            JOIN lines l ON l.id = c.line_id
            WHERE c.line_id = $1
            ORDER BY c.id DESC
            """,
            line_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT c.id, c.line_id, l.name AS line_name, c.old_limit_c,
                   c.new_limit_c, c.changed_by, c.changed_at
            FROM line_limit_changes c
            JOIN lines l ON l.id = c.line_id
            ORDER BY c.id DESC
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


async def list_readings(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(READING_SELECT + " ORDER BY r.id DESC")
    return web.json_response([_reading_json(r) for r in rows])


async def create_reading(request: web.Request) -> web.Response:
    user = require_writer(request)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    line_id = str(body.get("line_id", "")).strip()
    if not line_id:
        raise _error("请选择厢线", 400)
    probe_id = str(body.get("probe_id", "")).strip()
    if not probe_id:
        raise _error("探头编号不能为空", 400)
    temp_c = _parse_float(body.get("temp_c"), "温度")

    pool: asyncpg.Pool = request.app["pool"]
    async with pool.acquire() as conn:
        line = await conn.fetchrow("SELECT id, limit_c FROM lines WHERE id = $1", line_id)
        if not line:
            raise _error("厢线不存在，请先在分线上限页配置", 400)
        # 新提交吃该厢线现行上限（仅展示预期；真正快照在工人领单时写入）。
        row = await conn.fetchrow(
            """
            INSERT INTO probe_readings (line_id, probe_id, temp_c, status, created_by, created_at)
            VALUES ($1, $2, $3, 'pending', $4, now())
            RETURNING id, line_id, probe_id, temp_c, limit_c, verdict, reason,
                      status, created_by, created_at, processed_at
            """,
            line_id,
            probe_id,
            temp_c,
            user["username"],
        )
    return web.json_response(
        {
            "id": row["id"],
            "line_id": row["line_id"],
            "line_name": None,
            "probe_id": row["probe_id"],
            "temp_c": row["temp_c"],
            "limit_c": row["limit_c"],
            "verdict": row["verdict"],
            "reason": row["reason"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "processed_at": None,
            "current_limit_c": float(line["limit_c"]),
            "message": "已入队，后台工人将按领单当时该厢线上限判定",
        },
        status=201,
    )


async def on_startup(app: web.Application) -> None:
    pool = await create_pool()
    app["pool"] = pool
    await ensure_schema_async(pool)
    await seed_if_empty(pool)


async def on_cleanup(app: web.Application) -> None:
    pool: asyncpg.Pool = app.get("pool")
    if pool:
        await pool.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/api/lines", list_lines)
    app.router.add_post("/api/lines", create_line)
    app.router.add_put("/api/lines/{line_id}", update_line_limit)
    app.router.add_get("/api/line-limit-changes", list_line_changes)
    app.router.add_get("/api/readings", list_readings)
    app.router.add_post("/api/readings", create_reading)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
