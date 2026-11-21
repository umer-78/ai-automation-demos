// Airtable automation script (Team plan and above).
// Trigger: "When a record matches conditions" on Clients: Status is "Churned".
// Action: "Run a script" with one input variable: recordId.

const MAKE_OFFBOARDING_WEBHOOK = "https://hook.eu1.make.com/PASTE_YOUR_WEBHOOK_ID";

const { recordId } = input.config();
const payload = {
  event: "client.churned",
  airtable_record_id: recordId,
  run_id: `at${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
};

const response = await fetch(MAKE_OFFBOARDING_WEBHOOK, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
if (!response.ok) {
  throw new Error(`Make webhook returned HTTP ${response.status}`);
}
output.set("run_id", payload.run_id);
