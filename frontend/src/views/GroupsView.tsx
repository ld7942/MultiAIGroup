import { useEffect, useState } from "react";
import { api } from "../api";
import type { Group, Provider } from "../types";

interface Member {
  name: string;
  provider_id: string;
  persona: string;
}

export default function GroupsView() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [name, setName] = useState("我的 AI 群组");
  const [members, setMembers] = useState<Member[]>([
    { name: "AI 1", provider_id: "", persona: "" },
    { name: "AI 2", provider_id: "", persona: "" },
    { name: "AI 3", provider_id: "", persona: "" },
  ]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [ps, gs] = await Promise.all([api.providers(), api.groups()]);
      setProviders(ps);
      setGroups(gs);
      setMembers((prev) =>
        prev.map((m) => (m.provider_id ? m : { ...m, provider_id: ps[0]?.id || "" })),
      );
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const patch = (index: number, data: Partial<Member>) =>
    setMembers((prev) => prev.map((m, i) => (i === index ? { ...m, ...data } : m)));

  const addMember = () =>
    setMembers((prev) => [
      ...prev,
      { name: `AI ${prev.length + 1}`, provider_id: providers[0]?.id || "", persona: "" },
    ]);

  const removeMember = (index: number) =>
    setMembers((prev) => prev.filter((_, i) => i !== index));

  const save = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (members.some((m) => !m.provider_id)) throw new Error("每个成员都需要选择 Provider");
      await api.createGroup({ name, members });
      setNotice(`群组「${name}」已保存`);
      await load();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeGroup = async (id: string) => {
    try {
      await api.deleteGroup(id);
      await load();
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title">AI 群组</div>
          <div className="page-desc">
            把常用的 AI 组合保存成群组，开局时一键填充座位。群组只保存成员配置，不影响对局中的身份发放。
          </div>
        </div>
        <button className="btn sm" onClick={load}>刷新</button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="card" style={{ marginBottom: 14, color: "var(--accent-2)", fontSize: 12.5 }}>{notice}</div>}

      <div className="lobby-grid">
        <div className="card">
          <div className="card-title mb">新建群组</div>
          <label className="field mb">
            <span>群组名称</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="seat-editor">
            {members.map((member, index) => (
              <div className="seat-row" key={index} style={{ gridTemplateColumns: "30px minmax(0,1fr) minmax(130px,1.2fr) minmax(0,1.4fr) 30px" }}>
                <div className="seat-badge" style={{ background: "#2b3245", color: "var(--muted)" }}>{index + 1}</div>
                <input value={member.name} onChange={(e) => patch(index, { name: e.target.value })} placeholder={`AI ${index + 1}`} />
                <select value={member.provider_id} onChange={(e) => patch(index, { provider_id: e.target.value })}>
                  <option value="">选择 Provider</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}{p.model ? ` · ${p.model}` : ""}</option>
                  ))}
                </select>
                <input value={member.persona} onChange={(e) => patch(index, { persona: e.target.value })} placeholder="人设（可选）" />
                <button className="btn sm ghost" onClick={() => removeMember(index)} title="移除">×</button>
              </div>
            ))}
          </div>
          <div className="row mt">
            <button className="btn ghost sm" onClick={addMember}>+ 添加成员</button>
            <button className="btn primary right" onClick={save} disabled={busy}>
              {busy ? "保存中…" : "保存群组"}
            </button>
          </div>
        </div>

        <div className="card">
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="card-title">已有群组</div>
            <span className="chip right">{groups.length}</span>
          </div>
          <div className="match-list">
            {groups.map((g) => (
              <div key={g.id} className="match-item" style={{ cursor: "default" }}>
                <div className="flex1">
                  <div className="match-title">{g.name}</div>
                  <div className="match-meta">
                    {g.members.map((m) => m.name).join(" · ")}（{g.members.length} 人）
                  </div>
                </div>
                <button className="btn sm danger" onClick={() => removeGroup(g.id)}>删除</button>
              </div>
            ))}
            {!groups.length && <div className="empty">还没有群组</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
