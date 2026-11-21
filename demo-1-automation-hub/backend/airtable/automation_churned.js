// Airtable automation — trigger: "When a record matches conditions": Status is "Churned".
// Action: "Run a script". Add an input variable named recordId = the triggering record's ID.
// Paste the Make.com webhook URL of the "Client off-boarding" scenario below.
const MAKE_WEBHOOK = "https://hook.us1.make.com/REPLACE_WITH_OFFBOARDING_WEBHOOK";

const { recordId } = input.config();
const res = await fetch(MAKE_WEBHOOK, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ record_id: recordId }),
});
if (!res.ok) throw new Error(`Make webhook returned ${res.status}`);
output.set("sent", true);
