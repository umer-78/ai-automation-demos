// Airtable automation — trigger: "When a record is created" in Clients.
// Action: "Run a script". Add an input variable named recordId = the triggering record's ID.
// Paste the Make.com webhook URL of the "Client onboarding" scenario below.
const MAKE_WEBHOOK = "https://hook.us1.make.com/REPLACE_WITH_ONBOARDING_WEBHOOK";

const { recordId } = input.config();
const table = base.getTable("Clients");
const r = await table.selectRecordAsync(recordId);
if (!r) throw new Error(`Record ${recordId} not found`);

const payload = {
  record_id: r.id,
  name: r.getCellValueAsString("Name"),
  website: r.getCellValueAsString("Website"),
  industry: r.getCellValueAsString("Industry"),
  services: r.getCellValueAsString("Services"), // "SEO, Paid Ads"
  manager: r.getCellValueAsString("Account Manager"),
  manager_email: r.getCellValueAsString("Manager Email"),
};

const res = await fetch(MAKE_WEBHOOK, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
if (!res.ok) throw new Error(`Make webhook returned ${res.status}`);
output.set("sent", true);
