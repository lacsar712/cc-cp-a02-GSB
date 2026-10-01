# 冷链探头超温台

记录员按**厢线**上报探头编号与摄氏温度；不同厢线可配不同的**合格摄氏上限**。
后台工人用数据库行锁认领待处理队列，**领单瞬间抄下该厢线当时的上限**，
温度压在抄录上限以内判 **合格**，越线判 **超温**。

## 分线上限规则

- 记录员在顶栏「**分线上限**」落地页为每条厢线设置现行合格上限，每次改档写一条**改档流水**。
- 新提交的读数吃该厢线**现行上限**；读数进处理中后继续沿用**领单当时抄下的该线上限**，
  之后再改档不重判旧单，只影响改档后新领的单。
- 值班侧只能翻看各线上限与改档流水，**不可改线、不可报温**。
- 落地页只有三块：**分厢线表**、**改档流水**、**领单如何抄上限**；总览页不塞这些内容。

例：厢线甲上限 8℃ 改成 6℃ 后提交 7℃ → 超温（按 6℃）；再改回 8℃ 后提交 7℃ → 合格（按 8℃）。

## 技术栈

| 层 | 选型 |
|----|------|
| 接口 | Python aiohttp + asyncpg |
| 工人 | `worker.py`（psycopg，`FOR UPDATE SKIP LOCKED`） |
| 页面 | Preact + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3197 |
| 接口 | http://localhost:8197 |
| PostgreSQL | localhost:54397（库名 `coldchain`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| logger | log123456 | 记录员，可提交读数、配置分线上限 |
| watcher | watch123456 | 值班员，只读读数/分线上限/改档流水 |

## 启动

```bash
cd projects/18-coldchain-probe-desk
docker compose up --build
```

健康检查：`GET http://localhost:8197/api/health` → `{"status":"ok","service":"coldchain-probe-desk"}`

## 接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login` | - | 登录换 JWT |
| GET | `/api/lines` | 登录 | 分厢线表（含现行上限） |
| POST | `/api/lines` | 记录员 | 新增厢线（建档即写一条流水） |
| PUT | `/api/lines/{id}` | 记录员 | 修改该厢线合格上限并写流水 |
| GET | `/api/line-limit-changes` | 登录 | 改档流水（可 `?line_id=jia` 过滤） |
| GET | `/api/readings` | 登录 | 读数列表（含厢线与判定时抄录的上限） |
| POST | `/api/readings` | 记录员 | 提交读数（body 带 `line_id`、`probe_id`、`temp_c`） |

## 种子数据

| 厢线 | 探头 | 温度 | 该线上限 | 结论 |
|------|------|------|----------|------|
| 厢线甲（jia） | 探头A01 | 4.2℃ | 8℃ | 合格 |
| 厢线乙（yi） | 探头B02 | 12.5℃ | 8℃ | 超温 |

种子厢线默认上限均为 8℃，可在分线上限页随时改档。

## 本地开发（可选）

```bash
# 需本机 PostgreSQL 或仅起 db 容器
cd backend && pip install -r requirements.txt && python api.py
cd backend && python worker.py
cd frontend && npm install && npm run dev
```

接口进程默认监听容器内 **8000**，对外映射 **8197**。
