import clsx from "clsx";
import { useRef, useState, type FormEvent } from "react";
import { Skeleton, useToast } from "../components/ui";
import { accessCode, api, setAccessCode, type DataStatus } from "../lib/api";
import { count, timeAgo } from "../lib/format";
import { dataChanged, refreshStatus, useApi, useDataStatus } from "../lib/hooks";
import { Card, CardTitle, Section, btn } from "../world/Section";

type KeyField = { key: string; label: string; secret: boolean; placeholder: string; set: boolean; source: "saved" | "environment" | "none"; preview: string };
type Provider = { id: string; label: string; description: string; live: boolean; fields: KeyField[] };
type SettingsData = { owner_token_required: boolean; can_store: boolean; store_note: string; providers: Provider[] };
type Note = { name: string; title: string; text: string; updated_at: string | null };
type ImportResult = { rows: number; inserted: number; updated: number; skipped: string[]; skipped_count: number; flags: Record<string, number>; sample_removed: boolean };
type SyncResult = { accounts: number; inserted: number; updated: number; skipped: Record<string, number>; flags: Record<string, number> };

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const NEEDS: Record<string, string> = { product: "your product notes", anthropic: "a Claude API key", tavily: "a Tavily key" };
const field = "w-full rounded-[11px] border border-black/[0.1] bg-white px-3 py-2.5 text-[15px] outline-none transition focus:border-black/40 focus:ring-4 focus:ring-black/[0.05]";

export default function Settings() {
  const settings = useApi<SettingsData>("/api/settings");
  const status = useDataStatus();
  const [code, setCode] = useState(accessCode);
  const d = settings.data;
  const needCode = Boolean(d?.owner_token_required) && !code;
  return (
    <Section shot="settings" wide>
      <div className="space-y-4">
        <Card>
          <CardTitle aside={status ? <Badge s={status} /> : null}>Your CRM</CardTitle>
          {d?.owner_token_required && (
            <label className="mb-4 block text-[13.5px] text-ink-3">
              Owner access code (OWNER_TOKEN on the server, kept in this tab only)
              <input
                type="password"
                autoComplete="off"
                className={clsx(field, "mt-1")}
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  setAccessCode(e.target.value);
                }}
                placeholder="Paste the owner access code"
              />
            </label>
          )}
          {status ? <CrmPanel s={status} disabled={needCode} hubspot={Boolean(d?.providers.find((p) => p.id === "hubspot")?.live)} /> : <Skeleton className="h-40" />}
        </Card>
        {status?.mode === "real" && <NotesPanel disabled={needCode} />}
        <Card>
          <CardTitle>Connections</CardTitle>
          <p className="text-[15px] leading-relaxed text-ink-2">Keys are encrypted before they are stored, are never shown again in full, and work straight away. A lit socket on the board means that connection is live.</p>
          {d && !d.can_store && <p className="mt-3 rounded-xl bg-amber-soft px-4 py-3 text-[13.5px]">{d.store_note}</p>}
          {!d ? <Skeleton className="mt-4 h-64" /> : <ProviderList providers={d.providers} disabled={needCode} onSaved={(next) => settings.setData(next)} />}
        </Card>
      </div>
    </Section>
  );
}

function Badge({ s }: { s: DataStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={clsx("inline-block size-2 rounded-full", s.mode === "demo" ? "bg-amber" : "bg-moss")} />
      {s.label}
    </span>
  );
}

function CrmPanel({ s, disabled, hubspot }: { s: DataStatus; disabled: boolean; hubspot: boolean }) {
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"real" | "demo" | null>(null);
  const [imported, setImported] = useState<ImportResult | null>(null);
  const [synced, setSynced] = useState<SyncResult | null>(null);

  async function run<T>(key: string, fn: () => Promise<T>, done: (r: T) => void) {
    setBusy(key);
    try {
      done(await fn());
      refreshStatus();
      dataChanged();
    } catch (e) {
      toast("error", errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function importFile(e: FormEvent) {
    e.preventDefault();
    const f = file.current?.files?.[0];
    if (!f) return toast("error", "Choose a CSV file first.");
    if (f.size > 5_000_000) return toast("error", "That file is over 5 MB. Export fewer columns or split it.");
    const text = await f.text();
    await run("import", () => api.post<ImportResult>("/api/data/import", { csv: text }), (r) => {
      setImported(r);
      if (file.current) file.current.value = "";
      toast("success", `Imported ${count(r.rows)} accounts.`);
    });
  }

  const flags = (f: Record<string, number>) => `${f.stalled ?? 0} stalled, ${f.no_contact ?? 0} with no contact for 30+ days, ${f.upsell ?? 0} likely upsells`;

  return (
    <div className="space-y-4 text-[15px] leading-relaxed text-ink-2">
      {s.mode === "demo" ? (
        <p>You are looking at Acme Cloud Security's sample CRM: 50 fictional accounts. The leads are real companies with real sources. Load your own accounts here; the samples are deleted first, so your data never sits next to made-up rows.</p>
      ) : (
        <p>
          {s.accounts ? `${count(s.accounts)} accounts from ${s.crm_source === "hubspot" ? "HubSpot" : "your import"}.` : "No accounts yet: import a CSV or sync HubSpot."}
          {s.crm_source === "hubspot" && s.sync_minutes > 0 ? ` HubSpot is read again every ${s.sync_minutes} minutes.` : ""}
          {s.last_sync ? ` Last ${s.last_sync.kind === "hubspot_sync" ? "sync" : "import"} ${timeAgo(s.last_sync.at)}.` : ""}
        </p>
      )}
      {s.needs.length > 0 && (
        <p className="rounded-xl bg-amber-soft px-4 py-3 text-[14px] text-ink">
          Before the agent runs on your data it needs {s.needs.map((n) => NEEDS[n]).join(", ")}. The offline planner and the cached research only know the Acme demo.
        </p>
      )}

      <form onSubmit={importFile} className="rounded-2xl bg-sage-soft p-4">
        <div className="font-semibold text-ink">Import a CRM export</div>
        <p className="mt-1 text-[13.5px] text-ink-3">HubSpot, Salesforce, Pipedrive or a sheet: company, stage, amount, owner, last contacted and the date it entered its stage. Closed-lost rows are skipped; importing again updates accounts instead of doubling them.</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input ref={file} type="file" accept=".csv,text/csv" aria-label="CSV file" className="min-w-0 flex-1 text-[14px] file:mr-3 file:rounded-[9px] file:border-0 file:bg-white file:px-3 file:py-2 file:text-[14px] file:font-medium file:ring-1 file:ring-black/[0.12]" />
          <button type="submit" className={btn.primary} disabled={disabled || busy !== null}>
            {busy === "import" ? "Importing…" : "Import file"}
          </button>
          <button type="button" className={btn.quiet} onClick={() => void api.download("/api/data/template.csv", "crm-import-template.csv").catch((e) => toast("error", errText(e)))}>
            Template
          </button>
        </div>
        {imported && (
          <div className="mt-3 text-[13.5px]" role="status">
            <p className="text-moss">
              {count(imported.inserted)} new and {count(imported.updated)} updated accounts. The agent flagged {flags(imported.flags)}.{imported.sample_removed ? " The sample CRM was removed first." : ""}
            </p>
            {imported.skipped_count > 0 && (
              <details className="mt-1 text-crimson">
                <summary className="cursor-pointer">{count(imported.skipped_count)} rows left out (see why)</summary>
                <ul className="mt-1 list-disc pl-5">
                  {imported.skipped.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </form>

      <div className="flex flex-wrap items-center gap-2">
        {hubspot && (
          <button
            type="button"
            className={btn.primary}
            disabled={disabled || busy !== null}
            onClick={() =>
              run("hubspot", () => api.post<SyncResult>("/api/data/hubspot/sync"), (r) => {
                setSynced(r);
                toast("success", `Read ${count(r.accounts)} accounts from HubSpot.`);
              })
            }
          >
            {busy === "hubspot" ? "Reading HubSpot…" : "Sync HubSpot now"}
          </button>
        )}
        {confirm === null ? (
          <button type="button" className={btn.secondary} disabled={disabled || busy !== null} onClick={() => setConfirm(s.mode === "demo" ? "real" : "demo")}>
            {s.mode === "demo" ? "Start with my own data" : "Show the demo again"}
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-crimson-soft px-3 py-2 text-[13.5px] text-ink" role="alert">
            <span>{confirm === "real" ? "This deletes the sample accounts, leads, drafts and runs. Saved keys and notes stay." : "This deletes your accounts, leads and drafts and loads the sample CRM. Saved keys and notes stay."}</span>
            <button type="button" className={clsx(btn.primary, "!min-h-9 !bg-crimson")} disabled={busy !== null} onClick={() => void run(confirm, () => api.post<DataStatus>(`/api/data/${confirm}`), () => setConfirm(null))}>
              {busy === confirm ? "Working…" : confirm === "real" ? "Delete sample data" : "Delete and load demo"}
            </button>
            <button type="button" className={clsx(btn.quiet, "!min-h-9")} onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        )}
      </div>
      {synced && (
        <p className="text-[13.5px]" role="status">
          {count(synced.inserted)} new and {count(synced.updated)} updated accounts; {count(synced.skipped.closed_lost ?? 0)} closed-lost and {count(synced.skipped.no_company ?? 0)} deals without a company left out. Flags: {flags(synced.flags)}.
        </p>
      )}
    </div>
  );
}

function NotesPanel({ disabled }: { disabled: boolean }) {
  const toast = useToast();
  const notes = useApi<{ docs: Note[] }>(disabled ? null : "/api/data/notes");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const PLACEHOLDER: Record<string, string> = {
    product: "What you sell, who buys it, price points, the problems it solves, who you do not sell to.",
    competitors: "Who you compete with, where you win and where you lose.",
    deal_notes: "A few won and lost deals: who the buyer was, why they bought or walked away.",
  };
  async function save(name: string) {
    setBusy(name);
    try {
      notes.setData(await api.put<{ docs: Note[] }>(`/api/data/notes/${name}`, { text: edits[name] ?? "" }));
      setEdits((m) => {
        const next = { ...m };
        delete next[name];
        return next;
      });
      toast("success", "Saved. The next run reads it.");
      refreshStatus();
    } catch (e) {
      toast("error", errText(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <Card>
      <CardTitle>Your company notes</CardTitle>
      <p className="text-[15px] leading-relaxed text-ink-2">The agent reads these before every run and writes the ideal customer profile from them. Plain sentences work best.</p>
      {!notes.data ? (
        <Skeleton className="mt-4 h-60" />
      ) : (
        <div className="mt-4 space-y-4">
          {notes.data.docs.map((n) => (
            <div key={n.name}>
              <label className="block text-[13.5px] font-medium text-ink" htmlFor={`note-${n.name}`}>
                {n.title}
                {n.updated_at && <span className="ml-2 font-normal text-ink-3">saved {timeAgo(n.updated_at)}</span>}
              </label>
              <textarea id={`note-${n.name}`} className={clsx(field, "mt-1 min-h-[120px]")} value={edits[n.name] ?? n.text} placeholder={PLACEHOLDER[n.name]} onChange={(e) => setEdits((m) => ({ ...m, [n.name]: e.target.value }))} />
              <button type="button" className={clsx(btn.secondary, "mt-2 !min-h-9 !text-[14px]")} disabled={disabled || busy !== null || edits[n.name] === undefined} onClick={() => void save(n.name)}>
                {busy === n.name ? "Saving…" : "Save"}
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ProviderList({ providers, disabled, onSaved }: { providers: Provider[]; disabled: boolean; onSaved: (s: SettingsData) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, { ok: boolean; message: string }>>({});

  async function save(e: FormEvent, p: Provider) {
    e.preventDefault();
    const payload = Object.fromEntries(p.fields.map((f) => [f.key, values[f.key] ?? ""]).filter(([, v]) => v.trim()));
    if (!Object.keys(payload).length) return toast("error", "Type a value first.");
    setBusy(`save-${p.id}`);
    try {
      onSaved(await api.put<SettingsData>(`/api/settings/${p.id}`, { values: payload }));
      setValues({});
      setOpen(null);
      toast("success", `${p.label} saved. It is used from now on.`);
      refreshStatus();
      dataChanged();
    } catch (err) {
      toast("error", errText(err));
    } finally {
      setBusy(null);
    }
  }
  async function test(p: Provider) {
    setBusy(`test-${p.id}`);
    try {
      const r = await api.post<{ ok: boolean; message: string }>(`/api/settings/${p.id}/test`);
      setResult((m) => ({ ...m, [p.id]: r }));
    } catch (err) {
      setResult((m) => ({ ...m, [p.id]: { ok: false, message: errText(err) } }));
    } finally {
      setBusy(null);
    }
  }
  async function remove(p: Provider) {
    setBusy(`remove-${p.id}`);
    try {
      onSaved(await api.del<SettingsData>(`/api/settings/${p.id}`));
      toast("success", `${p.label} keys removed.`);
      refreshStatus();
      dataChanged();
    } catch (err) {
      toast("error", errText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <ul className="mt-4 divide-y divide-rule-soft">
      {providers.map((p) => {
        const editing = open === p.id;
        const anySaved = p.fields.some((f) => f.source === "saved");
        return (
          <li key={p.id} className="py-3.5">
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className={clsx("mt-1.5 inline-block size-2 shrink-0 rounded-full", p.live ? "bg-moss" : "bg-amber")} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold">{p.label}</span>
                  <span className={clsx("text-[12.5px]", p.live ? "text-moss" : "text-amber-ink")}>{p.live ? (p.id === "company" ? "set" : "live") : p.id === "company" ? "sample" : "not connected"}</span>
                </div>
                <p className="text-[13.5px] text-ink-3">{p.description}</p>
                {!editing && p.fields.some((f) => f.set) && (
                  <p className="mt-1 text-[12.5px] text-ink-3">
                    {p.fields
                      .filter((f) => f.set)
                      .map((f) => `${f.label}: ${f.preview} (${f.source === "saved" ? "saved here" : "from the server"})`)
                      .join("; ")}
                  </p>
                )}
                {p.id === "hubspot" && <p className="mt-1 text-[12.5px] text-ink-3">Private app scopes: crm.objects.companies.read, crm.objects.deals.read, crm.objects.contacts.read, crm.objects.owners.read. The app only reads HubSpot.</p>}
                {result[p.id] && <p className={clsx("mt-1 text-[13px]", result[p.id].ok ? "text-moss" : "text-crimson")}>{result[p.id].message}</p>}
              </div>
              <button type="button" className={clsx(btn.quiet, "!min-h-9 shrink-0 !text-[14px]")} aria-expanded={editing} onClick={() => setOpen(editing ? null : p.id)}>
                {editing ? "Close" : p.fields.some((f) => f.set) ? "Change" : p.id === "company" ? "Edit" : "Add key"}
              </button>
            </div>
            {editing && (
              <form onSubmit={(e) => save(e, p)} className="mt-3 space-y-3 pl-5">
                {p.fields.map((f) => (
                  <label key={f.key} className="block text-[13.5px] text-ink-3">
                    {f.label}
                    <input type={f.secret ? "password" : "text"} autoComplete="off" spellCheck={false} className={clsx(field, "mt-1")} value={values[f.key] ?? ""} placeholder={f.preview || f.placeholder} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
                  </label>
                ))}
                <div className="flex flex-wrap gap-2">
                  <button type="submit" className={btn.primary} disabled={busy !== null || disabled}>
                    {busy === `save-${p.id}` ? "Saving…" : "Save"}
                  </button>
                  <button type="button" className={btn.secondary} disabled={busy !== null || !p.live} onClick={() => void test(p)}>
                    {busy === `test-${p.id}` ? "Testing…" : "Test connection"}
                  </button>
                  {anySaved && (
                    <button type="button" className={clsx(btn.quiet, "text-crimson")} disabled={busy !== null} onClick={() => void remove(p)}>
                      Remove saved keys
                    </button>
                  )}
                </div>
              </form>
            )}
          </li>
        );
      })}
    </ul>
  );
}
