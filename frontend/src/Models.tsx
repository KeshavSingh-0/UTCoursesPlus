import { useEffect, useState } from "react";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { api } from "./api";
import type { SettingsView, Status } from "./api";
import { Note, PageHead } from "./ui";

type TestResult = { ok: boolean; provider: string; models: { id: string; name: string }[]; chosen: Record<string, { model: string; available: boolean }> };

const split = (spec: string): [string, string] => {
  const i = spec.indexOf(":");
  return i < 0 ? ["anthropic", spec] : [spec.slice(0, i), spec.slice(i + 1)];
};

export function ModelsScreen({ status, onChanged }: { status: Status; onChanged: () => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [def, setDef] = useState("");
  const [per, setPer] = useState<Record<string, string>>({});
  const [base, setBase] = useState("");
  const [busy, setBusy] = useState(false);

  const apply = (v: SettingsView) => { setView(v); setDef(v.default); setPer(v.tasks); setBase(v.custom_base_url); };
  useEffect(() => { api<SettingsView>("/api/settings").then(apply).catch((e) => setErr((e as Error).message)); }, []);
  if (!view) return <div><PageHead title="AI models" />{err ? <Note error>{err}</Note> : <p className="muted">Loading.</p>}</div>;

  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(""); setMsg("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const saveKey = (p: string) => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { keys: { [p]: keys[p] }, custom_base_url: p === "custom" ? base : undefined } }));
    setKeys({ ...keys, [p]: "" }); setMsg(`${view.providers[p].label} key saved on this computer. It will not be shown again.`); onChanged();
  });
  const removeKey = (p: string) => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { clear_keys: [p] } }));
    setMsg("Saved key removed."); onChanged();
  });
  const runTest = (p: string) => wrap(async () => {
    if (p === "custom" && base !== view.custom_base_url) await api("/api/settings", { method: "PUT", body: { custom_base_url: base } });
    const r = await api<TestResult>("/api/settings/test", { body: { provider: p, key: keys[p] || null } });
    setTests({ ...tests, [p]: r }); setMsg(`The ${view.providers[p].label} key works. ${r.models.length} models are available to it.`);
  });
  const saveModels = () => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { default: def, tasks: per } }));
    setMsg("Models saved."); onChanged();
  });

  const suggestions = (p: string) => Array.from(new Set([...(tests[p]?.models.map((m) => m.id) ?? []), ...view.providers[p].fallback_models]));
  const pick = (label: string, value: string, onChange: (v: string) => void, allowDefault?: boolean) => {
    const [p, m] = value ? split(value) : ["", ""];
    const provider = p || split(def)[0];
    const hasKey = view.providers[provider]?.key_source;
    const unavailable = value && tests[p]?.models.length && !tests[p].models.some((x) => x.id === m);
    return (
      <div className="field" key={label}>
        <span>{label}</span>
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <select aria-label={`${label} provider`} value={p} onChange={(e) => onChange(e.target.value ? `${e.target.value}:${view.providers[e.target.value].fallback_models[0] ?? ""}` : "")}>
            {allowDefault ? <option value="">Use the default ({def})</option> : null}
            {Object.entries(view.providers).map(([id, v]) => <option key={id} value={id}>{v.label}</option>)}
          </select>
          {p ? (
            <>
              <input type="text" aria-label={`${label} model`} list={`models-${label}`} value={m} spellCheck={false} onChange={(e) => onChange(`${p}:${e.target.value}`)} style={{ flex: "1 1 220px" }} />
              <datalist id={`models-${label}`}>{suggestions(p).map((x) => <option key={x} value={x} />)}</datalist>
            </>
          ) : null}
        </span>
        {p && !hasKey ? <span className="warn xs">No {view.providers[p].label} key yet. Add one above.</span> : null}
        {unavailable ? <span className="warn xs">Your {view.providers[p].label} key did not list {m}. It may be new, retired, or not enabled for your account.</span> : null}
      </div>
    );
  };

  return (
    <div>
      <PageHead title="AI models">Three jobs use a language model: turning plain English into preference changes, reading a pasted degree audit, and reading syllabi. Use any provider you have a key for: Claude, OpenAI, Gemini, Grok, or anything that speaks the OpenAI format. You can mix them, for example a cheap model for syllabi. Nothing else in the app needs one.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {msg ? <Note>{msg}</Note> : null}
      {status.llm_configured ? null : <Note>The default model's provider has no key, so the AI features are off until you add one or change the default.</Note>}

      <section className="block" aria-labelledby="key-h">
        <h2 id="key-h">API keys</h2>
        <p className="small muted" style={{ maxWidth: "78ch" }}>
          Keys are stored in <code>data/settings.json</code> on this computer, readable only by your user account, and each is sent only to its own provider. A key is never shown again after you save it and is not part of the git repository. Testing a key only asks which models it can use. Use keys you can revoke, and revoke any key you have pasted into a chat or an email.
        </p>
        <div className="stack" style={{ marginTop: 12, maxWidth: 760 }}>
          {Object.entries(view.providers).map(([p, v]) => (
            <div key={p} className="field">
              <span><strong>{v.label}</strong> {v.key_source === "saved" ? `Saved (${v.key_hint}).` : v.key_source === "environment" ? `From ${v.env_var} (${v.key_hint}).` : "No key."}</span>
              {p === "custom" ? (
                <input type="text" style={{ display: "block", width: "100%", marginTop: 6, marginBottom: 6 }} aria-label="Service address" placeholder="https://host/v1 (the address that ends before /chat/completions)" value={base} onChange={(e) => setBase(e.target.value)} />
              ) : null}
              <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <input type={show[p] ? "text" : "password"} autoComplete="off" spellCheck={false} aria-label={`${v.label} API key`} placeholder={v.key_prefix ? `Paste a key (starts with ${v.key_prefix})` : "Paste a key"} value={keys[p] ?? ""} onChange={(e) => setKeys({ ...keys, [p]: e.target.value })} style={{ flex: "1 1 260px" }} />
                <button className="btn" type="button" onClick={() => setShow({ ...show, [p]: !show[p] })} aria-label={show[p] ? "Hide the key" : "Show the key"}>{show[p] ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}</button>
                <button className="btn primary" disabled={busy || (keys[p] ?? "").trim().length < 20} onClick={() => saveKey(p)}><KeyRound size={14} aria-hidden /> Save key</button>
                <button className="btn" disabled={busy || (!(keys[p] ?? "").trim() && !v.key_source)} onClick={() => runTest(p)}>Test</button>
                {v.key_source === "saved" ? <button className="btn danger" disabled={busy} onClick={() => removeKey(p)}>Remove</button> : null}
              </span>
              {tests[p] ? (
                <details>
                  <summary className="small">Models this key can use ({tests[p].models.length})</summary>
                  <ul className="small mono" style={{ columns: 2 }}>{tests[p].models.map((m) => <li key={m.id}>{m.id}</li>)}</ul>
                </details>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className="block" aria-labelledby="mod-h">
        <h2 id="mod-h">Which model runs each job</h2>
        <p className="lede">Syllabus reading is the heaviest job, since each syllabus is sent in full, so a cheaper model there saves money; if its answers look thin, switch it back. Model names are free text with suggestions from the keys you have tested, so a model released after this app was written still works. Each provider's prices are on its own pricing page.</p>
        <div className="stack" style={{ maxWidth: 760 }}>
          {pick("Default model", def, setDef)}
          {Object.entries(view.task_names).map(([t, name]) => (
            pick(name, per[t] ?? "", (v) => setPer({ ...per, [t]: v }), true)
          ))}
          <div><button className="btn primary" disabled={busy} onClick={saveModels}>Save models</button></div>
        </div>
      </section>
    </div>
  );
}
