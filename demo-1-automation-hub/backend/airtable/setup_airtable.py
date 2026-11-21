"""Create the "Clients" table in an existing Airtable base (Airtable Web API, schema endpoint).

    AIRTABLE_TOKEN=pat... AIRTABLE_BASE_ID=app... python airtable/setup_airtable.py

The token needs the scopes data.records:read, data.records:write and schema.bases:write on that base.
"""
from __future__ import annotations

import os
import sys

import httpx

FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "Website", "type": "url"},
    {"name": "Industry", "type": "singleLineText"},
    {"name": "Services", "type": "multipleSelects", "options": {"choices": [
        {"name": "SEO"}, {"name": "Paid Ads"}, {"name": "Web Design"}]}},
    {"name": "Account Manager", "type": "singleLineText"},
    {"name": "Manager Email", "type": "email"},
    {"name": "Status", "type": "singleSelect", "options": {"choices": [
        {"name": "Active"}, {"name": "Onboarded"}, {"name": "Churned"}, {"name": "Archived"}]}},
    {"name": "Brief", "type": "multilineText"},
]


def main() -> int:
    token, base = os.environ.get("AIRTABLE_TOKEN", ""), os.environ.get("AIRTABLE_BASE_ID", "")
    table = os.environ.get("AIRTABLE_CLIENTS_TABLE", "Clients")
    if not (token and base):
        print("Set AIRTABLE_TOKEN and AIRTABLE_BASE_ID first.", file=sys.stderr)
        return 2
    h = {"Authorization": f"Bearer {token}"}
    existing = httpx.get(f"https://api.airtable.com/v0/meta/bases/{base}/tables", headers=h, timeout=20)
    existing.raise_for_status()
    if any(t["name"] == table for t in existing.json()["tables"]):
        print(f"Table '{table}' already exists; nothing to do.")
        return 0
    r = httpx.post(f"https://api.airtable.com/v0/meta/bases/{base}/tables", headers=h, timeout=20,
                   json={"name": table, "description": "Northwind Digital clients (fake demo data)", "fields": FIELDS})
    r.raise_for_status()
    print(f"Created table '{table}' ({r.json()['id']}). Now add the two automations in airtable/README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
