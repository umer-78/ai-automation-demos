/** "2026-11-20" -> "20 Nov" (dates are calendar days, so format them in UTC). */
export const day = (iso?: string | null) =>
  iso ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : "—";

/** A log timestamp in the viewer's own time zone. */
export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

const EMOJI: Record<string, string> = { rocket: "🚀", wave: "👋", warning: "⚠️", mega: "📣", art: "🎨" };

/** Slack mrkdwn to plain text: *bold* -> bold, <url|label> -> label, :rocket: -> the emoji. */
export const slackText = (s: string) =>
  s.replace(/<([^|>]+)\|([^>]+)>/g, "$2").replace(/\*(.+?)\*/g, "$1").replace(/:([a-z_]+):/g, (m, k: string) => EMOJI[k] ?? m);

/** Why something wasn't sent, without repeating ourselves. */
export const notSent = (what: string, detail: string) =>
  /not configured|not set/i.test(detail) ? `${what} isn't set up on this server.` : detail;
