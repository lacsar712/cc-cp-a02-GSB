import { useEffect, useState } from "preact/hooks";

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(
    d.getHours()
  )}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtTemp(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toString();
}

export function LimitsPage({ lines, history, isWriter, authHeaders, reload }) {
  const [drafts, setDrafts] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    reload();
  }, []);

  async function save(lineId) {
    const raw = drafts[lineId];
    const limit_c = parseFloat(raw);
    if (!Number.isFinite(limit_c)) {
      setError("上限必须是数字");
      return;
    }
    setError("");
    setMsg("");
    setBusyId(lineId);
    try {
      const res = await fetch(`/api/lines/${encodeURIComponent(lineId)}`, {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify({ limit_c }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || "改档失败");
        return;
      }
      setMsg(data.message || "已改档");
      setDrafts((d) => {
        const next = { ...d };
        delete next[lineId];
        return next;
      });
      await reload();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <p class="sub" style={{ marginBottom: "1rem" }}>
        不同厢线可配不同合格摄氏上限。{isWriter ? "记录员可为每条厢线设上限。" : "值班侧只可查看，不可改线、不可报温。"}
      </p>

      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>分厢线上限</h2>
        <table>
          <thead>
            <tr>
              <th>厢线</th>
              <th>名称</th>
              <th>现行上限（℃）</th>
              <th>最近改档</th>
              {isWriter && <th>改档</th>}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const draft = drafts[l.id];
              return (
                <tr key={l.id}>
                  <td>{l.id}</td>
                  <td>{l.name}</td>
                  <td>{fmtTemp(l.limit_c)}</td>
                  <td>
                    {l.updated_by ? `${fmtTime(l.updated_at)} · ${l.updated_by}` : "—"}
                  </td>
                  {isWriter && (
                    <td>
                      <div class="inline-edit">
                        <input
                          type="number"
                          step="0.1"
                          value={draft !== undefined ? draft : l.limit_c}
                          onInput={(e) =>
                            setDrafts({ ...drafts, [l.id]: e.target.value })
                          }
                          style={{ minWidth: "90px" }}
                        />
                        <button
                          type="button"
                          disabled={busyId === l.id || draft === undefined || draft === ""}
                          onClick={() => save(l.id)}
                        >
                          设上限
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
        {error && <p class="err">{error}</p>}
        {msg && <p class="ok">{msg}</p>}
      </div>

      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>改档流水</h2>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>厢线</th>
              <th>原上限（℃）</th>
              <th>新上限（℃）</th>
              <th>改档人</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id}>
                <td>{fmtTime(h.changed_at)}</td>
                <td>
                  {h.line_name ? `${h.line_name}（${h.line_id}）` : h.line_id}
                </td>
                <td>{h.old_limit_c === null ? "—" : fmtTemp(h.old_limit_c)}</td>
                <td>{fmtTemp(h.new_limit_c)}</td>
                <td>{h.changed_by}</td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colspan="5">暂无改档记录</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div class="card">
        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>领单如何抄上限</h2>
        <ol class="explain">
          <li>
            记录员提交读数时选择厢线；新提交的单状态为「待处理」，此时还不带上限。
          </li>
          <li>
            后台工人领单（状态转为「处理中」）的同一事务里，把该厢线的
            <strong>现行上限抄录</strong>到这张单上，作为专属快照。
          </li>
          <li>
            判定只认快照：温度压在抄录上限以内判「合格」，越线判「超温」。
          </li>
          <li>
            已进处理中或已完成的单继续用领单当时抄下的上限；之后改档不追溯，
            只有改档之后新领的单才吃新上限。
          </li>
          <li>
            例：厢线甲上限改成 6℃ 后提交 7℃，应判「超温」；再改回 8℃ 后提交
            7℃，应判「合格」。
          </li>
          <li>值班侧可翻各线上限与改档流水，但不可改线，也不可报温。</li>
        </ol>
      </div>
    </div>
  );
}
