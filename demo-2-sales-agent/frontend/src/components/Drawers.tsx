import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { Account, Lead } from "../lib/api";
import { CATEGORY_LABEL, dayMonth, hostOf, money, shortDate, SIGNAL_LABEL, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Chip, Drawer, ErrorNote, FlagChip, ScoreBar, ScoreLegend, Skeleton, StatusChip } from "./ui";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-3 py-1.5 text-[14px]">
      <dt className="text-ink-3">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function DraftLinks({ drafts }: { drafts: NonNullable<Lead["drafts"]> }) {
  if (!drafts.length) return <p className="text-[14px] text-ink-3">No drafts yet.</p>;
  return (
    <ul className="space-y-2">
      {drafts.map((d) => (
        <li key={d.id} className="flex flex-wrap items-center gap-2 text-[14px]">
          <Link to={`/approvals?draft=${d.id}`} className="link font-semibold">
            {d.subject}
          </Link>
          <StatusChip status={d.status} />
          <span className="text-[12.5px] text-ink-3">{timeAgo(d.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

export function LeadDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: lead, error } = useApi<Lead>(id ? `/api/leads/${id}` : null);
  return (
    <Drawer
      open={id !== null}
      onClose={onClose}
      title={
        lead ? (
          <div>
            <h2 className="display text-[26px]">{lead.company}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <StatusChip status={lead.status} />
              <span className="text-[13px] text-ink-3">{lead.industry}</span>
            </div>
          </div>
        ) : (
          <Skeleton className="h-8 w-48" />
        )
      }
    >
      {error && <ErrorNote message={error} />}
      {lead && (
        <div className="space-y-6">
          <section>
            <ScoreBar parts={lead.score_parts} score={lead.score} dimmed={lead.status === "excluded"} />
            <div className="mt-2">
              <ScoreLegend />
            </div>
            <p className="mt-3 text-[14px] text-ink-2">{lead.score_reason}</p>
          </section>
          <section>
            <h3 className="heading mb-1 text-[15px]">Why now</h3>
            <p className="text-[15px]">{lead.reason}</p>
            {lead.excluded_reason && <p className="mt-2 text-[14px] text-crimson">{lead.excluded_reason}</p>}
          </section>
          <section>
            <h3 className="heading mb-2 text-[15px]">What the research found</h3>
            <ul className="space-y-3">
              {lead.facts.map((f) => (
                <li key={f.url} className="rounded-lg border border-rule bg-sheet p-3">
                  <p className="text-[15px]">{f.fact}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
                    <Chip tone="amber">{SIGNAL_LABEL[f.type] ?? f.type}</Chip>
                    {f.date && <span>{shortDate(f.date)}</span>}
                    <a href={f.url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">
                      {hostOf(f.url)} <ExternalLink className="size-3.5" aria-hidden />
                    </a>
                    {f.source === "cache" && <span>(research cache)</span>}
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3 className="heading mb-1 text-[15px]">Profile</h3>
            <dl>
              <Row label="Category">{CATEGORY_LABEL[lead.category] ?? lead.category}</Row>
              <Row label="Size">{lead.size_band === "unknown" ? "Not confirmed" : `${lead.size_band} employees`}</Row>
              <Row label="Region">{lead.region === "unknown" ? "Not confirmed" : lead.region}</Row>
              <Row label="Cloud">{lead.cloud_native === "yes" ? "Cloud-native" : lead.cloud_native === "no" ? "Mostly on-premise" : "Not confirmed"}</Row>
              {lead.domain && (
                <Row label="Website">
                  <a className="link" href={`https://${lead.domain}`} target="_blank" rel="noreferrer">
                    {lead.domain}
                  </a>
                </Row>
              )}
              <Row label="Contacts">None stored. The agent never invents names or email addresses.</Row>
            </dl>
          </section>
          <section>
            <h3 className="heading mb-2 text-[15px]">Drafts</h3>
            <DraftLinks drafts={lead.drafts ?? []} />
          </section>
        </div>
      )}
    </Drawer>
  );
}

export function AccountDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: acc, error } = useApi<Account>(id ? `/api/accounts/${id}` : null);
  return (
    <Drawer
      open={id !== null}
      onClose={onClose}
      title={
        acc ? (
          <div>
            <h2 className="display text-[26px]">{acc.company}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
              <Chip tone="sage">{acc.stage}</Chip>
              <span>Owner {acc.owner}</span>
              <span>{acc.industry}</span>
            </div>
          </div>
        ) : (
          <Skeleton className="h-8 w-48" />
        )
      }
    >
      {error && <ErrorNote message={error} />}
      {acc && (
        <div className="space-y-6">
          {acc.score !== null ? (
            <section>
              <ScoreBar parts={acc.score_parts} score={acc.score} />
              <p className="mt-3 text-[14px] text-ink-2">{acc.score_reason}</p>
            </section>
          ) : (
            <p className="text-[14px] text-ink-3">Not analysed yet. Run the agent to score this account.</p>
          )}
          {acc.flags && acc.flags.length > 0 && (
            <section className="space-y-2">
              {acc.flags.map((f) => (
                <div key={f} className="flex items-start gap-2 text-[14px]">
                  <FlagChip flag={f} />
                  <span>{acc.flag_reasons?.[f]}</span>
                </div>
              ))}
            </section>
          )}
          <section>
            <dl>
              <Row label={acc.stage === "Customer" ? "ARR" : "Deal value"}>{money(acc.stage === "Customer" ? acc.arr : acc.deal_value)}</Row>
              {acc.plan && (
                <Row label="Plan">
                  {acc.plan}, {acc.cloud_accounts_used} of {acc.cloud_accounts_limit} cloud accounts
                </Row>
              )}
              {acc.renewal_date && <Row label="Renewal">{shortDate(acc.renewal_date)}</Row>}
              <Row label="In stage since">{shortDate(acc.stage_entered_at)}</Row>
              <Row label="Last contact">{acc.last_contact ? `${shortDate(acc.last_contact)} (${timeAgo(acc.last_contact)})` : "Never"}</Row>
              <Row label="Contact">
                {acc.contact_name}, {acc.contact_title}
                <div className="text-[13px] text-ink-3">{acc.contact_email}</div>
              </Row>
              <Row label="Size">{acc.size?.toLocaleString()} employees, {acc.region}, {acc.cloud_provider}</Row>
              <Row label="Notes">{acc.notes}</Row>
            </dl>
          </section>
          <section>
            <h3 className="heading mb-2 text-[15px]">Activity</h3>
            <ol className="relative space-y-3 border-l border-rule pl-4">
              {(acc.activity ?? []).map((a) => (
                <li key={a.id} className="text-[14px]">
                  <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-paper bg-sage" aria-hidden />
                  <div className="text-[12.5px] text-ink-3">
                    {dayMonth(a.occurred_at)}, {a.kind}, {a.direction}
                  </div>
                  <div>{a.summary}</div>
                </li>
              ))}
            </ol>
          </section>
          <section>
            <h3 className="heading mb-2 text-[15px]">Follow-up drafts</h3>
            <DraftLinks drafts={acc.drafts ?? []} />
          </section>
        </div>
      )}
    </Drawer>
  );
}
