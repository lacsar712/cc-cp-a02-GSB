# 冷链探头超温台

记录员按厢线上报探头编号与摄氏温度，后台工人用数据库行锁认领待处理队列，
**领单时抄录该厢线现行上限**作为快照，温度压在快照上限以内判 **合格**、越线判 **超温**。

不同厢线可配不同的合格摄氏上限；已在处理中或已完成的单继续用领单当时抄下的上限，改档不追溯。

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
| logger | log123456 | 记录员，可提交读数、可为每条厢线改上限 |
| watcher | watch123456 | 值班员，只读：可翻读数、各线上限与改档流水，不可改线、不可报温 |

## 分线上限

顶栏「分线上限」入口进入落地页，含三块，与总览分离：

1. **分厢线表**：每条厢线的现行摄氏上限；记录员可就地改档，值班员只读。
2. **改档流水**：每次改档的时间、厢线、原上限→新上限、改档人。
3. **领单如何抄上限**：说明快照规则——领单（置为处理中）同一事务把该厢线现行上限抄到单上，
   判定只认快照；改档后只有新领的单吃新上限。

验收场景：厢线甲上限改成 **6℃** 后提交 **7℃** 判超温；改回 **8℃** 后再提交 **7℃** 判合格。

## 接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/lines` | 登录 | 各厢线现行上限 |
| GET | `/api/lines/history` | 登录 | 改档流水（最新在前） |
| PUT | `/api/lines/{line_id}` | 记录员 | 改上限，body `{"limit_c": 6}`，同值拒绝并自动写流水 |
| GET | `/api/readings` | 登录 | 读数列表，含厢线与领单抄录上限 `limit_c` |
| POST | `/api/readings` | 记录员 | 提交 `probe_id`、`line_id`、`temp_c`，入队 pending |

## 启动

```bash
cd projects/18-coldchain-probe-desk
docker compose up --build
```

健康检查：`GET http://localhost:8197/api/health` → `{"status":"ok","service":"coldchain-probe-desk"}`

## 种子数据

厢线：厢线甲（甲）、厢线乙（乙），默认上限均为 8℃。

| 探头 | 厢线 | 温度 | 结论 |
|------|------|------|------|
| 探头A01 | 甲 | 4.2℃ | 合格 |
| 探头B02 | 乙 | 12.5℃ | 超温 |

## 本地开发（可选）

```bash
# 需本机 PostgreSQL 或仅起 db 容器
cd backend && pip install -r requirements.txt && python api.py
cd backend && python worker.py
cd frontend && npm install && npm run dev
```

接口进程默认监听容器内 **8000**，对外映射 **8197**。
