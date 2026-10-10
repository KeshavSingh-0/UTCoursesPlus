import { useEffect, useState } from "react";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { api } from "./api";
import type { SettingsView, Status } from "./api";
import { Note, PageHead } from "./ui";

// Prices per million tokens (input / output) from Anthropic's list as of October 2026. Check their pricing page for current rates.
const INFO: Record<string, string> = {
  "claude-opus-5-5": "most capable everyday model, about $4 in and $20 out",
  "claude-sonnet-5-5": "fast and capable, about $2 in and $10 out",
  "claude-haiku-5-5": "cheapest, about $0.10 in and $0.50 out",
  "claude-fable-5-1": "most capable overall, about $10 in and $50 out",
};
type TestResult = { ok: boolean; models: { id: string; name: string }[]; chosen: Record<string, { model: string; available: boolean }> };

export function ModelsScreen({ status, onChanged }: { status: Status; onChanged: () => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [key, setKey] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState<TestResult | null>(null);
  const [def, setDef] = useState("");
  const [per, setPer] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const apply = (v: SettingsView) => { setView(v); setDef(v.default_model); setPer(v.models); };
  useEffect(() => { api<SettingsView>("/api/settings").then(apply).catch((e) => setErr((e as Error).message)); }, []);
  if (!view) return <div><PageHead title="AI models" />{err ? <Note error>{err}</Note> : <p className="muted">Loading.</p>}</div>;

  const options = Array.from(new Set([...(test?.models.map((m) => m.id) ?? []), ...view.fallback_models, def, ...Object.values(per).filter(Boolean)]));
  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(""); setMsg("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const saveKey = () => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { anthropic_key: key } }));
    setKey(""); setMsg("Key saved on this computer. It will not be shown again."); onChanged();
  });
  const removeKey = () => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { clear_key: true } }));
    setTest(null); setMsg("Saved key removed."); onChanged();
  });
  const runTest = () => wrap(async () => {
    const r = await api<TestResult>("/api/settings/test", { body: { anthropic_key: key || null } });
    setTest(r); setMsg(`The key works. ${r.models.length} models are available to it.`);
  });
  const saveModels = () => wrap(async () => {
    apply(await api<SettingsView>("/api/settings", { method: "PUT", body: { default_model: def, models: per } }));
    setMsg("Models saved."); onChanged();
  });
  const sourceText = view.key_source === "saved" ? `Saved in this app (${view.key_hint}).` : view.key_source === "environment" ? `Read from the ANTHROPIC_API_KEY environment variable (${view.key_hint}).` : "No key yet.";

  return (
    <div>
      <PageHead title="AI models">Three jobs use a language model: turning plain English into preference changes, reading a pasted degree audit, and reading syllabi. Paste your Anthropic API key here and choose which model runs each one. Nothing else in the app needs it.</PageHead>
      {err ? <Note error>{err}</Note> : null}
      {msg ? <Note>{msg}</Note> : null}

      <section className="block" aria-labelledby="key-h">
        <h2 id="key-h">API key</h2>
        <p className="lede">{sourceText} {status.llm_configured ? "" : "The AI features are switched off until a key is set."}</p>
        <div className="row" style={{ alignItems: "end" }}>
          <label className="field" style={{ flex: "1 1 360px", maxWidth: 520 }}>
            <span>Paste a key (starts with sk-ant-)</span>
            <span style={{ display: "flex", gap: 6 }}>
              <input type={show ? "text" : "password"} autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} style={{ flex: 1 }} />
              <button className="btn" type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide the key" : "Show the key"}>{show ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}</button>
            </span>
          </label>
          <button className="btn primary" disabled={busy || key.trim().length < 20} onClick={saveKey}><KeyRound size={14} aria-hidden /> Save key</button>
          <button className="btn" disabled={busy || (!key.trim() && !view.key_source)} onClick={runTest}>Test the key</button>
          {view.key_source === "saved" ? <button className="btn danger" disabled={busy} onClick={removeKey}>Remove saved key</button> : null}
        </div>
        <p className="small muted" style={{ marginTop: 10, maxWidth: "78ch" }}>
          The key is stored in <code>data/settings.json</code> on this computer, readable only by your user account, and is sent only to Anthropic. It is never shown again after you save it, and it is not part of the git repository. Testing a key only asks which models it can use, which costs nothing. Anyone who can use your account on this computer can read the file, so use a key you can revoke, and revoke any key you have pasted into a chat or an email.
        </p>
      </section>

      <section className="block" aria-labelledby="mod-h">
        <h2 id="mod-h">Which model runs each job</h2>
        <p className="lede">Syllabus reading is the heaviest job, since each syllabus is sent in full. A cheaper model there saves money; if its answers look thin, switch it back. Only Anthropic models are supported.</p>
        <div className="stack" style={{ maxWidth: 760 }}>
          <label className="field">
            <span>Default model</span>
            <select value={def} onChange={(e) => setDef(e.target.value)}>{options.map((m) => <option key={m} value={m}>{m}{INFO[m] ? `: ${INFO[m]}` : ""}</option>)}</select>
          </label>
          {Object.entries(view.tasks).map(([t, name]) => (
            <label className="field" key={t}>
              <span>{name}</span>
              <select value={per[t] ?? ""} onChange={(e) => setPer({ ...per, [t]: e.target.value })}>
                <option value="">Use the default ({def})</option>
                {options.map((m) => <option key={m} value={m}>{m}{INFO[m] ? `: ${INFO[m]}` : ""}</option>)}
              </select>
              {test && per[t] && test.chosen[t] && !test.chosen[t].available ? <span className="warn xs">Your key did not list {per[t]}. It may be new, retired, or not enabled for your account.</span> : null}
            </label>
          ))}
          <div><button className="btn primary" disabled={busy} onClick={saveModels}>Save models</button></div>
        </div>
        <p className="small muted" style={{ marginTop: 10, maxWidth: "78ch" }}>Prices are per million tokens, input and output, from Anthropic's list in October 2026; check their pricing page for current rates. A typical syllabus is a few thousand tokens.</p>
        {test ? (
          <details style={{ marginTop: 10 }}>
            <summary className="small">Models your key can use ({test.models.length})</summary>
            <ul className="small mono" style={{ columns: 2 }}>{test.models.map((m) => <li key={m.id}>{m.id}</li>)}</ul>
          </details>
        ) : null}
      </section>
    </div>
  );
}
