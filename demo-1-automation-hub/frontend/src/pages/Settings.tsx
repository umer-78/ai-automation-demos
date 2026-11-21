import clsx from "clsx";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Field, Skeleton, useToast } from "../components/ui";
import { accessCode, api, setAccessCode, type DataStatus } from "../lib/api";
import { count, shortDate, timeAgo } from "../lib/format";
import { dataChanged, refreshStatus, useApi, useStatus } from "../lib/hooks";
import { Card, CardTitle, Section, btn } from "../world/Section";

type KeyField = { key: string; label: string; secret: boolean; placeholder: string; set: boolean; source: "saved" | "environment" | "none"; preview: string };
type Provider = { id: string; label: string; description: string; live: boolean; fields: KeyField[] };
type SettingsData = { owner_token_required: boolean; can_store: boolean; store_note: string; providers: Provider[] };
type Platform = "google_ads" | "meta_ads" | "search_console" | "ga4" | "seo_fee";
type ClientLinks = { id: number; name: string; status: string; accounts: Partial<Record<Platform, string>> };
type Accounts = { clients: ClientLinks[]; ready: Record<string, boolean>; google_signed_in: boolean; google_oauth_ready: boolean };
type Found = Record<string, { items: { id: string; name: string; currency?: string }[]; error: string | null; ready: boolean }>;
type ImportResult = { rows: number; inserted: number; updated: number; new_clients: string[]; skipped: string[]; skipped_count: number; period: { start: string; end: string }; demo_removed: boolean };
type SyncResult = { fetched: number; inserted: number; updated: number; warnings: string[] };

const PLATFORMS: { key: Platform; label: string; placeholder: string; needs: string }[] = [
  { key: "google_ads", label: "Google Ads customer ID", placeholder: "123-456-7890", needs: "google_ads" },
  { key: "meta_ads", label: "Meta ad account", placeholder: "act_1234567890", needs: "meta_ads" },
  { key: "search_console", label: "Search Console property", placeholder: "sc-domain:example.com", needs: "search_console" },
  { key: "ga4", label: "Analytics property ID", placeholder: "123456789", needs: "ga4" },
  { key: "seo_fee", label: "SEO fee per month", placeholder: "1500", needs: "search_console" },
];
const GOOGLE_RESULT: Record<string, [ok: boolean, text: string]> = {
  connected: [true, "Signed in with Google. Google Ads, Search Console and Analytics can be read now."],
  cancelled: [false, "Google sign-in was cancelled."],
  expired: [false, "That sign-in link expired. Start it again."],
  failed: [false, "Google refused the sign-in. Check the client ID, secret and redirect URI."],
};
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Settings() {
  const toast = useToast();
  const settings = useApi<SettingsData>("/api/settings");
  const status = useStatus();
  const [code, setCode] = useState(accessCode);
  const [params, setParams] = useSearchParams();

  useEffect(() => {
    const result = params.get("google");
    if (!result || !GOOGLE_RESULT[result]) return;
    const [ok, text] = GOOGLE_RESULT[result];
    toast(ok ? "success" : "failure", text);
    params.delete("google");
    setParams(params, { replace: true });
    void settings.reload();
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function rememberCode(v: string) {
    setCode(v);
    setAccessCode(v);
  }

  const d = settings.data;
  const data = status?.data;
  const needCode = Boolean(d?.owner_token_required) && !code;
  return (
    <Section shot="settings" wide>
      <div className="space-y-4">
        <Card>
          <CardTitle aside={data ? <DataBadge data={data} /> : null}>Your data</CardTitle>
          {d?.owner_token_required && (
            <div className="mb-4">
              <Field label="Owner access code" hint="Set as OWNER_TOKEN on the server. Kept in this tab only.">
                <input type="password" autoComplete="off" className="field" value={code} onChange={(e) => rememberCode(e.target.value)} placeholder="Paste the owner access code" />
              </Field>
            </div>
          )}
          {data ? <DataPanel data={data} disabled={needCode} /> : <Skeleton className="h-40" />}
        </Card>
        {data?.mode === "real" && <AccountsPanel disabled={needCode} />}
        <Card>
          <CardTitle>Connections</CardTitle>
          <p className="text-[15px] leading-relaxed text-[#3f444c]">
            Keys are encrypted before they are stored, are never shown again in full, and work straight away. A lit socket on the board means that connection is live.
          </p>
          {d && !d.can_store && <p className="mt-4 rounded-xl bg-[#fff7e6] px-4 py-3 text-[13.5px] text-[#7a4b00]">{d.store_note}</p>}
          {!d ? <Skeleton className="mt-5 h-64" /> : <ProviderList providers={d.providers} disabled={needCode} onSaved={(next) => settings.setData(next)} />}
        </Card>
      </div>
    </Section>
  );
}

function DataBadge({ data }: { data: DataStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={clsx("inline-block size-2 rounded-full", data.mode === "demo" ? "bg-[#f5a524]" : "bg-[#0f9f88]")} />
      {data.label}
    </span>
  );
}

function DataPanel({ data, disabled }: { data: DataStatus; disabled: boolean }) {
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
      toast("failure", errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function importFile(e: FormEvent) {
    e.preventDefault();
    const f = file.current?.files?.[0];
    if (!f) return toast("failure", "Choose a CSV file first.");
    if (f.size > 5_000_000) return toast("failure", "That file is over 5 MB. Split it by month and import each part.");
    const text = await f.text();
    await run("import", () => api.post<ImportResult>("/api/data/import", { csv: text }), (r) => {
      setImported(r);
      if (file.current) file.current.value = "";
      toast("success", `Imported ${count(r.rows)} rows.`);
    });
  }

  const switchMode = (to: "real" | "demo") =>
    run(to, () => api.post<DataStatus>(`/api/data/${to}`), () => {
      setConfirm(null);
      setImported(null);
      toast("success", to === "real" ? "Demo data deleted. Import a file or link your accounts." : "The demo is loaded again.");
    });

  return (
    <div className="space-y-4 text-[15px] leading-relaxed text-[#3f444c]">
      {data.mode === "demo" ? (
        <p>
          You are looking at five sample clients. Their cost per click, cost per lead and conversion rates follow the published 2026 medians for their industries; the sources are listed on the Reporting page. Load your own numbers here: the samples are deleted first, so real and sample figures never mix.
        </p>
      ) : (
        <p>
          Every figure comes from {data.live_sources.length ? <strong className="font-semibold text-black">{data.live_sources.join(", ")}</strong> : "your imported files"}
          {data.live_sources.length ? ` and any files you import. New numbers are pulled every ${data.sync_minutes} minutes for complete days up to yesterday.` : ". Link ad accounts below to keep the numbers current on their own."}
          {data.last_sync && ` Last sync ${timeAgo(data.last_sync.at)} (${data.last_sync.status}).`}
        </p>
      )}

      <form onSubmit={importFile} className="rounded-2xl bg-[#f6f7f9] p-4">
        <div className="font-semibold text-black">Import a CSV export</div>
        <p className="mt-1 text-[13.5px] text-[#5B616B]">
          Google Ads, Meta Ads Manager or any report with date, client, channel, clicks, spend and conversions. Day-first and month-first dates both work; rows for days already loaded are replaced, not doubled.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input ref={file} type="file" accept=".csv,text/csv" aria-label="CSV file" className="min-w-0 flex-1 text-[14px] file:mr-3 file:rounded-[9px] file:border-0 file:bg-white file:px-3 file:py-2 file:text-[14px] file:font-medium file:ring-1 file:ring-black/[0.12]" />
          <button type="submit" className={btn.primary} disabled={disabled || busy !== null}>
            {busy === "import" ? "Importing…" : "Import file"}
          </button>
          <button type="button" className={btn.quiet} onClick={() => void api.download("/api/data/template.csv", "northwind-import-template.csv").catch((e) => toast("failure", errText(e)))}>
            Template
          </button>
        </div>
        {imported && (
          <div className="mt-3 text-[13.5px]" role="status">
            <p className="text-[#0b7d6b]">
              {count(imported.rows)} rows from {shortDate(imported.period.start)} to {shortDate(imported.period.end)}: {count(imported.inserted)} new, {count(imported.updated)} replaced
              {imported.new_clients.length ? `, new clients: ${imported.new_clients.join(", ")}` : ""}.
              {imported.demo_removed ? " The demo clients were removed first." : ""}
            </p>
            {imported.skipped_count > 0 && (
              <details className="mt-1 text-[#9a3412]">
                <summary className="cursor-pointer">{count(imported.skipped_count)} rows left out (see why)</summary>
                <ul className="mt-1 list-disc pl-5">
                  {imported.skipped.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </form>

      <div className="flex flex-wrap items-center gap-2">
        {data.mode === "real" && data.live_sources.length > 0 && (
          <button
            type="button"
            className={btn.primary}
            disabled={disabled || busy !== null}
            onClick={() =>
              run("sync", () => api.post<SyncResult>("/api/data/sync"), (r) => {
                setSynced(r);
                toast(r.warnings.length ? "failure" : "success", r.warnings.length ? "Synced, with warnings below." : `Synced ${count(r.fetched)} rows.`);
              })
            }
          >
            {busy === "sync" ? "Syncing…" : "Sync now"}
          </button>
        )}
        {confirm === null ? (
          <button type="button" className={btn.secondary} disabled={disabled || busy !== null} onClick={() => setConfirm(data.mode === "demo" ? "real" : "demo")}>
            {data.mode === "demo" ? "Start with real data" : "Show the demo again"}
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-[#fef5f4] px-3 py-2 text-[13.5px] text-[#7a271a]" role="alert">
            <span>{confirm === "real" ? "This deletes the demo clients, their numbers and run history. Saved keys stay." : "This deletes your imported and synced numbers and loads the sample clients. Saved keys stay."}</span>
            <button type="button" className={clsx(btn.primary, "!min-h-9 !bg-[#B42318]")} disabled={busy !== null} onClick={() => void switchMode(confirm)}>
              {busy === confirm ? "Working…" : confirm === "real" ? "Delete demo data" : "Delete and load demo"}
            </button>
            <button type="button" className={clsx(btn.quiet, "!min-h-9")} onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        )}
      </div>
      {synced && (
        <p className="text-[13.5px]" role="status">
          Pulled {count(synced.fetched)} rows: {count(synced.inserted)} new, {count(synced.updated)} updated.
          {synced.warnings.map((w) => (
            <span key={w} className="mt-1 block text-[#9a3412]">
              {w}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function AccountsPanel({ disabled }: { disabled: boolean }) {
  const toast = useToast();
  const accounts = useApi<Accounts>(disabled ? null : "/api/data/accounts");
  const [found, setFound] = useState<Found | null>(null);
  const [edits, setEdits] = useState<Record<string, Partial<Record<Platform, string>>>>({});
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const a = accounts.data;
  const anyReady = a ? Object.values(a.ready).some(Boolean) : false;

  async function findAccounts() {
    setBusy("find");
    try {
      setFound(await api.get<Found>("/api/data/discover"));
    } catch (e) {
      toast("failure", errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function save(key: string, body: { client_id?: number; name?: string; accounts: Partial<Record<Platform, string>> }) {
    setBusy(key);
    try {
      accounts.setData(await api.put<Accounts>("/api/data/accounts", body));
      setEdits((m) => ({ ...m, [key]: {} }));
      if (!body.client_id) setNewName("");
      toast("success", "Accounts linked. Use Sync now to pull their numbers.");
      refreshStatus();
    } catch (e) {
      toast("failure", errText(e));
    } finally {
      setBusy(null);
    }
  }

  const shown = PLATFORMS.filter((p) => a?.ready[p.needs]);
  const inputs = (key: string, current: Partial<Record<Platform, string>>) => (
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      {shown.map((p) => (
        <label key={p.key} className="block text-[12.5px] text-[#5B616B]">
          {p.label}
          <input
            className="field mt-1 w-full"
            list={found?.[p.key]?.items.length ? `found-${p.key}` : undefined}
            spellCheck={false}
            autoComplete="off"
            placeholder={p.placeholder}
            value={edits[key]?.[p.key] ?? current[p.key] ?? ""}
            onChange={(e) => setEdits((m) => ({ ...m, [key]: { ...m[key], [p.key]: e.target.value } }))}
          />
        </label>
      ))}
    </div>
  );

  return (
    <Card>
      <CardTitle aside={a ? `${a.clients.length} client${a.clients.length === 1 ? "" : "s"}` : null}>Client accounts</CardTitle>
      <p className="text-[15px] leading-relaxed text-[#3f444c]">
        Link each client to the accounts its numbers come from. Search Console gives SEO clicks and impressions, Analytics gives the conversions from organic search, and the SEO fee is spread over each day of the month as the channel's spend.
      </p>
      {PLATFORMS.map((p) =>
        found?.[p.key]?.items.length ? (
          <datalist key={p.key} id={`found-${p.key}`}>
            {found[p.key].items.map((it) => (
              <option key={it.id} value={it.id}>
                {it.name}
                {it.currency ? ` (${it.currency})` : ""}
              </option>
            ))}
          </datalist>
        ) : null,
      )}
      {!a ? (
        <Skeleton className="mt-4 h-40" />
      ) : !anyReady ? (
        <p className="mt-3 rounded-xl bg-[#fff7e6] px-4 py-3 text-[13.5px] text-[#7a4b00]">
          Connect Google or Meta under Connections, then link {a.clients.length ? a.clients.map((c) => c.name).join(", ") : "your clients"} to their accounts here.
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className={btn.secondary} disabled={disabled || !anyReady || busy !== null} onClick={() => void findAccounts()}>
              {busy === "find" ? "Looking…" : "Find my accounts"}
            </button>
            {found && (
              <span className="text-[13.5px] text-[#5B616B]">
                {Object.entries(found)
                  .filter(([, v]) => v.ready)
                  .map(([k, v]) => (v.error ? `${PLATFORMS.find((p) => p.key === k)?.label}: ${v.error}` : `${v.items.length} ${PLATFORMS.find((p) => p.key === k)?.label.toLowerCase()}s`))
                  .join("; ")}
              </span>
            )}
          </div>
          <ul className="mt-3 divide-y divide-black/[0.07]">
            {a.clients.map((c) => (
              <li key={c.id} className="py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-semibold">{c.name}</span>
                  <button type="button" className={clsx(btn.quiet, "!min-h-9 !text-[14px]")} disabled={disabled || busy !== null || !Object.keys(edits[`c${c.id}`] ?? {}).length} onClick={() => void save(`c${c.id}`, { client_id: c.id, accounts: edits[`c${c.id}`] ?? {} })}>
                    {busy === `c${c.id}` ? "Saving…" : "Save"}
                  </button>
                </div>
                {inputs(`c${c.id}`, c.accounts)}
              </li>
            ))}
            <li className="py-3">
              <Field label="Add a client">
                <input className="field" value={newName} maxLength={200} onChange={(e) => setNewName(e.target.value)} placeholder="Client name" />
              </Field>
              {inputs("new", {})}
              <button type="button" className={clsx(btn.primary, "mt-3")} disabled={disabled || busy !== null || !newName.trim()} onClick={() => void save("new", { name: newName.trim(), accounts: edits.new ?? {} })}>
                {busy === "new" ? "Adding…" : "Add client"}
              </button>
            </li>
          </ul>
        </>
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
  const redirect = useApi<{ redirect_uri: string }>("/api/data/google/redirect-uri");

  async function save(e: FormEvent, p: Provider) {
    e.preventDefault();
    const payload = Object.fromEntries(p.fields.map((f) => [f.key, values[f.key] ?? ""]).filter(([, v]) => v.trim()));
    if (!Object.keys(payload).length) return toast("failure", "Type a value first.");
    setBusy(`save-${p.id}`);
    try {
      onSaved(await api.put<SettingsData>(`/api/settings/${p.id}`, { values: payload }));
      setValues({});
      setOpen(null);
      toast("success", `${p.label} saved. It is used from now on.`);
      refreshStatus();
      dataChanged();
    } catch (err) {
      toast("failure", errText(err));
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
      toast("failure", errText(err));
    } finally {
      setBusy(null);
    }
  }

  async function googleSignIn() {
    setBusy("google-sign-in");
    try {
      const r = await api.post<{ url: string }>("/api/data/google/start");
      window.location.assign(r.url);
    } catch (err) {
      toast("failure", errText(err));
      setBusy(null);
    }
  }

  return (
    <ul className="mt-4 divide-y divide-black/[0.07]">
      {providers.map((p) => {
        const editing = open === p.id;
        const anySaved = p.fields.some((f) => f.source === "saved");
        const oauthReady = p.id === "google" && p.fields.filter((f) => f.key !== "google_oauth_refresh_token").every((f) => f.set);
        return (
          <li key={p.id} className="py-3.5">
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className={clsx("mt-1.5 inline-block size-2 shrink-0 rounded-full", p.live ? "bg-[#0f9f88]" : "bg-[#f5a524]")} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold">{p.label}</span>
                  <span className={clsx("text-[12.5px]", p.live ? "text-[#0b7d6b]" : "text-[#9a6b00]")}>{p.live ? "live" : "not connected"}</span>
                </div>
                <p className="text-[13.5px] text-[#5B616B]">{p.description}</p>
                {!editing && p.fields.some((f) => f.set) && (
                  <p className="mt-1 text-[12.5px] text-[#5B616B]">
                    {p.fields
                      .filter((f) => f.set)
                      .map((f) => `${f.label}: ${f.preview} (${f.source === "saved" ? "saved here" : "from the server"})`)
                      .join("; ")}
                  </p>
                )}
                {p.id === "google" && (
                  <div className="mt-2 space-y-1.5 text-[12.5px] text-[#5B616B]">
                    {redirect.data && (
                      <p>
                        Redirect URI for your Google OAuth client: <code className="break-all rounded bg-black/[0.05] px-1 py-0.5 text-[12px] text-black">{redirect.data.redirect_uri}</code>
                      </p>
                    )}
                    <button type="button" className={clsx(btn.secondary, "!min-h-9 !text-[14px]")} disabled={disabled || !oauthReady || busy !== null} onClick={() => void googleSignIn()}>
                      {busy === "google-sign-in" ? "Opening Google…" : p.live ? "Sign in with Google again" : "Sign in with Google"}
                    </button>
                  </div>
                )}
                {result[p.id] && <p className={clsx("mt-1 text-[13px]", result[p.id].ok ? "text-[#0b7d6b]" : "text-[#B42318]")}>{result[p.id].message}</p>}
              </div>
              <button type="button" className={clsx(btn.quiet, "!min-h-9 shrink-0 !text-[14px]")} aria-expanded={editing} onClick={() => setOpen(editing ? null : p.id)}>
                {editing ? "Close" : p.fields.some((f) => f.set) ? "Change" : "Add key"}
              </button>
            </div>
            {editing && (
              <form onSubmit={(e) => save(e, p)} className="mt-3 space-y-3 pl-5">
                {p.fields.map((f) => (
                  <Field key={f.key} label={f.label}>
                    <input
                      type={f.secret ? "password" : "text"}
                      autoComplete="off"
                      spellCheck={false}
                      className="field"
                      value={values[f.key] ?? ""}
                      placeholder={f.preview || f.placeholder}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  </Field>
                ))}
                <div className="flex flex-wrap gap-2">
                  <button type="submit" className={btn.primary} disabled={busy !== null || disabled}>
                    {busy === `save-${p.id}` ? "Saving…" : "Save"}
                  </button>
                  <button type="button" className={btn.secondary} disabled={busy !== null || !p.live} onClick={() => void test(p)}>
                    {busy === `test-${p.id}` ? "Testing…" : "Test connection"}
                  </button>
                  {anySaved && (
                    <button type="button" className={clsx(btn.quiet, "text-[#B42318]")} disabled={busy !== null} onClick={() => void remove(p)}>
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
