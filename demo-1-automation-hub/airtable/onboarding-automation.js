// Airtable automation script (Team plan and above: "Run a script" is not available on Free).
// On the Free plan use the webhook bridge instead (see README.md); the payload is identical.
//
// Trigger: "When a record matches conditions" on the Clients table:
//   Status is "New" AND Name, Services and Account Manager are not empty.
// Action: "Run a script". Add one input variable: recordId = the triggering record's Airtable record ID.

const MAKE_ONBOARDING_WEBHOOK = "https://hook.eu1.make.com/PASTE_YOUR_WEBHOOK_ID";

const { recordId } = input.config();
const table = base.getTable("Clients");
const record = await table.selectRecordAsync(recordId);
if (!record) throw new Error(`Record ${recordId} not found`);

const services = (record.getCellValue("Services") || []).map((option) => option.name);
const payload = {
  event: "client.created",
  airtable_record_id: record.id,
  name: record.getCellValueAsString("Name"),
  website: record.getCellValueAsString("Website"),
  industry: record.getCellValueAsString("Industry"),
  services,
  manager: record.getCellValueAsString("Account Manager"),
  manager_email: record.getCellValueAsString("Manager Email"),
  monthly_budget: record.getCellValue("Monthly Budget"),
  simulate_failure: Boolean(record.getCellValue("Simulate Failure")),
  run_id: `at${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
};

const response = await fetch(MAKE_ONBOARDING_WEBHOOK, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
if (!response.ok) {
  throw new Error(`Make webhook returned HTTP ${response.status}`);
}

// Move the row out of "New" so the automation never fires twice for the same client.
await table.updateRecordAsync(record.id, { Status: { name: "Onboarding" } });
output.set("run_id", payload.run_id);
