import { useCallback, useEffect, useState } from "preact/hooks";
import { LimitsPage } from "./LimitsPage.jsx";

const TOKEN_KEY = "coldchain_token";
const USER_KEY = "coldchain_user";

function verdictClass(v, status) {
  if (v === "合格") return "tag pass";
  if (v === "超温") return "tag fail";
  if (status === "pending" || status === "processing") return "tag wait";
  return "tag wait";
}

function displayVerdict(row) {
  if (row.verdict) return row.verdict;
  if (row.status === "pending") return "待处理";
  if (row.status === "processing") return "处理中";
  return "—";
}

function statusText(s) {
  if (s === "pending") return "待处理";
  if (s === "processing") return "处理中";
  if (s === "done") return "已完成";
  return s;
}

function fmtTemp(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toString();
}

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [view, setView] = useState("overview");
  const [loginForm, setLoginForm] = useState({ username: "logger", password: "log123456" });
  const [submitForm, setSubmitForm] = useState({ probe_id: "", line_id: "", temp_c: "" });
  const [rows, setRows] = useState([]);
  const [lines, setLines] = useState([]);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const authHeaders = useCallback(() => {
    const h = { "Content-Type": "application/json" };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, [token]);

  const loadReadings = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/readings", { headers: authHeaders() });
    if (!res.ok) {
      setError("加载列表失败，请重新登录");
      return;
    }
    setRows(await res.json());
  }, [token, authHeaders]);

  const loadLines = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/lines", { headers: authHeaders() });
    if (res.ok) setLines(await res.json());
  }, [token, authHeaders]);

  const loadHistory = useCallback(async () => {
    if (!token) return;
    const res = await fetch("/api/lines/history", { headers: authHeaders() });
    if (res.ok) setHistory(await res.json());
  }, [token, authHeaders]);

  const reloadLimits = useCallback(async () => {
    await Promise.all([loadLines(), loadHistory()]);
  }, [loadLines, loadHistory]);

  useEffect(() => {
    if (!token) {
      setView("overview");
      return undefined;
    }
    loadReadings();
    loadLines();
    const t = setInterval(() => {
      loadReadings();
      if (view === "limits") reloadLimits();
    }, 3000);
    return () => clearInterval(t);
  }, [loadReadings, loadLines, reloadLimits, view, token]);

  useEffect(() => {
    if (view === "limits") reloadLimits();
  }, [view, reloadLimits]);

  // 厢线列表就绪后给提交表单一个默认厢线。
  useEffect(() => {
    if (!submitForm.line_id && lines.length > 0) {
      setSubmitForm((f) => ({ ...f, line_id: lines[0].id }));
    }
  }, [lines, submitForm.line_id]);

  async function onLogin(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });
      if (!res.ok) {
        setError("用户名或密码错误");
        return;
      }
      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(
        USER_KEY,
        JSON.stringify({ username: data.username, role: data.role })
      );
      setToken(data.access_token);
      setUser({ username: data.username, role: data.role });
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    setRows([]);
    setLines([]);
    setHistory([]);
  }

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setMsg("");
    setLoading(true);
    try {
      const res = await fetch("/api/readings", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          probe_id: submitForm.probe_id,
          line_id: submitForm.line_id,
          temp_c: parseFloat(submitForm.temp_c),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "提交失败");
        return;
      }
      setMsg(data.message || "已提交");
      setSubmitForm((f) => ({ probe_id: "", line_id: f.line_id, temp_c: "" }));
      await loadReadings();
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div class="wrap">
        <h1>冷链探头超温台</h1>
        <p class="sub">记录员按厢线提交探头编号与摄氏温度，后台工人领单时抄录该厢线现行上限后判定。</p>
        <div class="card">
          <form onSubmit={onLogin}>
            <div class="row">
              <label>
                用户名
                <input
                  value={loginForm.username}
                  onInput={(e) =>
                    setLoginForm({ ...loginForm, username: e.target.value })
                  }
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginForm.password}
                  onInput={(e) =>
                    setLoginForm({ ...loginForm, password: e.target.value })
                  }
                />
              </label>
              <button type="submit" disabled={loading}>
                登录
              </button>
            </div>
            {error && <p class="err">{error}</p>}
          </form>
          <p class="sub" style={{ marginBottom: 0 }}>
            记录员 logger / log123456 · 值班员 watcher / watch123456
          </p>
        </div>
      </div>
    );
  }

  const isWriter = user?.role === "writer";

  return (
    <div class="wrap">
      <div class="topbar">
        <div>
          <h1>冷链探头超温台</h1>
          <nav class="nav">
            <button
              type="button"
              class={view === "overview" ? "navbtn active" : "navbtn"}
              onClick={() => setView("overview")}
            >
              总览
            </button>
            <button
              type="button"
              class={view === "limits" ? "navbtn active" : "navbtn"}
              onClick={() => setView("limits")}
            >
              分线上限
            </button>
          </nav>
        </div>
        <div class="user">
          {user?.username}（{isWriter ? "记录员" : "值班员"}）
          <button type="button" class="secondary" style={{ marginLeft: "0.5rem" }} onClick={logout}>
            退出
          </button>
        </div>
      </div>

      {view === "limits" ? (
        <LimitsPage
          lines={lines}
          history={history}
          isWriter={isWriter}
          authHeaders={authHeaders}
          reload={reloadLimits}
        />
      ) : (
        <>
          {isWriter && (
            <div class="card">
              <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>提交读数</h2>
              <form onSubmit={onSubmit}>
                <div class="row">
                  <label>
                    厢线
                    <select
                      required
                      value={submitForm.line_id}
                      onChange={(e) =>
                        setSubmitForm({ ...submitForm, line_id: e.target.value })
                      }
                    >
                      {lines.map((l) => (
                        <option value={l.id}>
                          {l.name}（上限 {fmtTemp(l.limit_c)}℃）
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    探头编号
                    <input
                      required
                      value={submitForm.probe_id}
                      onInput={(e) =>
                        setSubmitForm({ ...submitForm, probe_id: e.target.value })
                      }
                      placeholder="例如 探头C03"
                    />
                  </label>
                  <label>
                    温度（℃）
                    <input
                      required
                      type="number"
                      step="0.1"
                      value={submitForm.temp_c}
                      onInput={(e) =>
                        setSubmitForm({ ...submitForm, temp_c: e.target.value })
                      }
                    />
                  </label>
                  <button type="submit" disabled={loading}>
                    提交
                  </button>
                </div>
                {error && <p class="err">{error}</p>}
                {msg && <p class="ok">{msg}</p>}
              </form>
            </div>
          )}

          <div class="card">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>读数列表</h2>
            <table>
              <thead>
                <tr>
                  <th>编号</th>
                  <th>厢线</th>
                  <th>探头</th>
                  <th>温度℃</th>
                  <th>领单抄录上限℃</th>
                  <th>结论</th>
                  <th>说明</th>
                  <th>状态</th>
                  <th>提交人</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{r.line_name ? `${r.line_name}（${r.line_id}）` : "—"}</td>
                    <td>{r.probe_id}</td>
                    <td>{fmtTemp(r.temp_c)}</td>
                    <td>{r.status === "pending" ? "待领单" : fmtTemp(r.limit_c)}</td>
                    <td>
                      <span class={verdictClass(r.verdict, r.status)}>
                        {displayVerdict(r)}
                      </span>
                    </td>
                    <td>{r.reason || "—"}</td>
                    <td>{statusText(r.status)}</td>
                    <td>{r.created_by}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colspan="9">暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
