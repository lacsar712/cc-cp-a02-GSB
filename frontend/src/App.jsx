import { useCallback, useEffect, useState } from "preact/hooks";

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
  return { pending: "待处理", processing: "处理中", done: "已判定" }[s] || s;
}

function fmtLimit(v) {
  return v === null || v === undefined ? "—" : `${Number(v)}℃`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
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
  const [view, setView] = useState("home");
  const [loginForm, setLoginForm] = useState({ username: "logger", password: "log123456" });
  const [submitForm, setSubmitForm] = useState({ line_id: "", probe_id: "", temp_c: "" });
  const [rows, setRows] = useState([]);
  const [lines, setLines] = useState([]);
  const [changes, setChanges] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const isWriter = user?.role === "writer";

  const authHeaders = useCallback(() => {
    const h = { "Content-Type": "application/json" };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }, [token]);

  const loadReadings = useCallback(async () => {
    const res = await fetch("/api/readings", { headers: authHeaders() });
    if (!res.ok) return;
    setRows(await res.json());
  }, [authHeaders]);

  const loadLines = useCallback(async () => {
    const res = await fetch("/api/lines", { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    setLines(data);
    setSubmitForm((f) => (f.line_id ? f : { ...f, line_id: data[0]?.id || "" }));
  }, [authHeaders]);

  const loadChanges = useCallback(async () => {
    const res = await fetch("/api/line-limit-changes", { headers: authHeaders() });
    if (!res.ok) return;
    setChanges(await res.json());
  }, [authHeaders]);

  useEffect(() => {
    if (!token) return undefined;
    loadLines();
    const t = setInterval(loadLines, 3000);
    return () => clearInterval(t);
  }, [loadLines, token]);

  useEffect(() => {
    if (!token) return undefined;
    if (view === "home") {
      loadReadings();
      const t = setInterval(loadReadings, 3000);
      return () => clearInterval(t);
    }
    loadChanges();
    const t = setInterval(loadChanges, 3000);
    return () => clearInterval(t);
  }, [loadReadings, loadChanges, view, token]);

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
    setChanges([]);
    setView("home");
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
          line_id: submitForm.line_id,
          probe_id: submitForm.probe_id,
          temp_c: parseFloat(submitForm.temp_c),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "提交失败");
        return;
      }
      setMsg(data.message || "已提交");
      setSubmitForm({ ...submitForm, probe_id: "", temp_c: "" });
      await loadReadings();
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div class="wrap">
        <h1>冷链探头超温台</h1>
        <p class="sub">记录员按厢线提交探头编号与摄氏温度，后台工人按领单当时该厢线上限判定合格或超温。</p>
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

  const currentLine = lines.find((l) => l.id === submitForm.line_id);

  return (
    <div class="wrap">
      <div class="topbar">
        <div>
          <h1>冷链探头超温台</h1>
          <p class="sub">各厢线可配各自合格摄氏上限，温度压在该线上限以内判合格，越线判超温。</p>
        </div>
        <div class="user">
          {user?.username}（{isWriter ? "记录员" : "值班员"}）
          <button
            type="button"
            class="secondary"
            style={{ marginLeft: "0.5rem" }}
            onClick={() => {
              setView(view === "limits" ? "home" : "limits");
              setError("");
              setMsg("");
            }}
          >
            {view === "limits" ? "返回总览" : "分线上限"}
          </button>
          <button type="button" class="secondary" style={{ marginLeft: "0.5rem" }} onClick={logout}>
            退出
          </button>
        </div>
      </div>

      {view === "limits" ? (
        <LimitsPage
          isWriter={isWriter}
          lines={lines}
          changes={changes}
          authHeaders={authHeaders}
          onChanged={async () => {
            await loadLines();
            await loadChanges();
          }}
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
                      {lines.length === 0 && <option value="">（暂无厢线）</option>}
                      {lines.map((l) => (
                        <option value={l.id} key={l.id}>
                          {l.name}
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
                {currentLine && (
                  <p class="sub" style={{ margin: "0.5rem 0 0", fontSize: "0.8rem" }}>
                    {currentLine.name}现行合格上限 {fmtLimit(currentLine.limit_c)}
                    ；新单按该线上限判定，进处理中后改档不影响本单。
                  </p>
                )}
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
                  <th>判定上限</th>
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
                    <td>{r.line_name || "—"}</td>
                    <td>{r.probe_id}</td>
                    <td>{r.temp_c}</td>
                    <td>{fmtLimit(r.limit_c)}</td>
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

function LimitsPage({ isWriter, lines, changes, authHeaders, onChanged }) {
  const [drafts, setDrafts] = useState({});
  const [newLine, setNewLine] = useState({ id: "", name: "", limit_c: "8" });
  const [busyId, setBusyId] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  function draftFor(l) {
    return Object.prototype.hasOwnProperty.call(drafts, l.id) ? drafts[l.id] : String(l.limit_c);
  }

  async function saveLimit(l) {
    const value = parseFloat(draftFor(l));
    if (Number.isNaN(value)) {
      setErr("合格上限必须是数字");
      return;
    }
    setErr("");
    setOk("");
    setBusyId(l.id);
    try {
      const res = await fetch(`/api/lines/${encodeURIComponent(l.id)}`, {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ limit_c: value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(data.detail || "改档失败");
        return;
      }
      setOk(`${l.name}上限已改为 ${value}℃`);
      await onChanged();
    } finally {
      setBusyId("");
    }
  }

  async function addLine(e) {
    e.preventDefault();
    setErr("");
    setOk("");
    const value = parseFloat(newLine.limit_c);
    if (Number.isNaN(value)) {
      setErr("合格上限必须是数字");
      return;
    }
    setBusyId("__new__");
    try {
      const res = await fetch("/api/lines", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ id: newLine.id.trim(), name: newLine.name.trim(), limit_c: value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(data.detail || "新增厢线失败");
        return;
      }
      setOk(`已新增厢线 ${data.name}，上限 ${value}℃`);
      setNewLine({ id: "", name: "", limit_c: "8" });
      await onChanged();
    } finally {
      setBusyId("");
    }
  }

  return (
    <>
      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>分厢线表</h2>
        <table>
          <thead>
            <tr>
              <th>厢线</th>
              <th>代码</th>
              <th>现行合格上限</th>
              <th>最后修改</th>
              {isWriter && <th>改档</th>}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const draft = draftFor(l);
              const same = parseFloat(draft) === Number(l.limit_c);
              return (
                <tr key={l.id}>
                  <td>{l.name}</td>
                  <td>{l.id}</td>
                  <td>{fmtLimit(l.limit_c)}</td>
                  <td>
                    {l.updated_by} · {fmtTime(l.updated_at)}
                  </td>
                  {isWriter && (
                    <td>
                      <div class="inline-edit">
                        <input
                          type="number"
                          step="0.1"
                          value={draft}
                          onInput={(e) => setDrafts({ ...drafts, [l.id]: e.target.value })}
                        />
                        <span class="unit">℃</span>
                        <button
                          type="button"
                          disabled={busyId === l.id || same || Number.isNaN(parseFloat(draft))}
                          onClick={() => saveLimit(l)}
                        >
                          保存
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              );
            })}
            {lines.length === 0 && (
              <tr>
                <td colspan={isWriter ? 5 : 4}>暂无厢线</td>
              </tr>
            )}
          </tbody>
        </table>

        {isWriter ? (
          <form onSubmit={addLine} style={{ marginTop: "1rem" }}>
            <div class="row">
              <label>
                新厢线代码
                <input
                  required
                  value={newLine.id}
                  onInput={(e) => setNewLine({ ...newLine, id: e.target.value })}
                  placeholder="例如 bing"
                />
              </label>
              <label>
                名称
                <input
                  required
                  value={newLine.name}
                  onInput={(e) => setNewLine({ ...newLine, name: e.target.value })}
                  placeholder="例如 厢线丙"
                />
              </label>
              <label>
                合格上限（℃）
                <input
                  required
                  type="number"
                  step="0.1"
                  value={newLine.limit_c}
                  onInput={(e) => setNewLine({ ...newLine, limit_c: e.target.value })}
                />
              </label>
              <button type="submit" disabled={busyId === "__new__"}>
                新增厢线
              </button>
            </div>
          </form>
        ) : (
          <p class="sub" style={{ margin: "0.75rem 0 0", fontSize: "0.85rem" }}>
            值班侧仅可查看各线上限与改档流水，不可改线、不可报温。
          </p>
        )}
        {err && <p class="err">{err}</p>}
        {ok && <p class="ok">{ok}</p>}
      </div>

      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>改档流水</h2>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>厢线</th>
              <th>原上限</th>
              <th>新上限</th>
              <th>改档人</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => (
              <tr key={c.id}>
                <td>{fmtTime(c.changed_at)}</td>
                <td>{c.line_name}</td>
                <td>{c.old_limit_c === null ? "—（建档）" : fmtLimit(c.old_limit_c)}</td>
                <td>{fmtLimit(c.new_limit_c)}</td>
                <td>{c.changed_by}</td>
              </tr>
            ))}
            {changes.length === 0 && (
              <tr>
                <td colspan="5">暂无改档记录</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>领单如何抄上限</h2>
        <ol class="rules">
          <li>记录员提交读数时，读数先按所选厢线入待处理队列。</li>
          <li>后台工人领单（行锁认领）的一瞬间，把<strong>该厢线当时的现行合格上限</strong>抄进这张单子。</li>
          <li>判定只认单子上抄下来的上限：温度 ≤ 抄录上限判合格，越线判超温。</li>
          <li>已进处理中或已判定的单子，随后厢线再改档也<strong>不会重判</strong>；改档只影响改档之后新领的单。</li>
          <li>每次新建厢线与改档都在上方“改档流水”留痕，值班员可查不可改。</li>
        </ol>
      </div>
    </>
  );
}
