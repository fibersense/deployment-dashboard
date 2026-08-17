#!/usr/bin/env python3
"""
Pulls current deployment data from Jira and regenerates index.html.

Required environment variables (set as GitHub Actions secrets):
  JIRA_DOMAIN      e.g. fibersense.atlassian.net
  JIRA_EMAIL       the Jira account email used for API auth
  JIRA_API_TOKEN   an Atlassian API token for that account

Run manually:  python3 scripts/generate_dashboard.py
"""

import os
import re
import sys
import json
import base64
import datetime
import urllib.request
import urllib.parse
import urllib.error

JIRA_DOMAIN = os.environ.get("JIRA_DOMAIN", "").strip()
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "").strip()
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "").strip()
PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SDO").strip()

if not (JIRA_DOMAIN and JIRA_EMAIL and JIRA_API_TOKEN):
    print("Missing JIRA_DOMAIN / JIRA_EMAIL / JIRA_API_TOKEN environment variables.", file=sys.stderr)
    sys.exit(1)

AUTH = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
BASE = f"https://{JIRA_DOMAIN}/rest/api/3"

# Custom field IDs discovered for this Jira instance's checklists.
CF_INTERNET = "customfield_10076"
CF_HARDWARE = "customfield_10490"
CF_FIBER = "customfield_10491"

IP_STAGES = ["Ordered", "IP Address Allocated", "Circuit Delivered",
             "Cross-Connect Ordered", "Cross-Connect Delivered", "Connected", "Live"]
FIBER_STAGES = ["KMLs Delivered", "Fiber Delivered", "Fiber Connected", "Validated", "Calibrated"]
HW_STAGES = ["Deployment Questionnaire Completed", "Design Completed", "BoM Quote", "Procurement",
             "Staging", "Shipping", "Received", "Installed", "Configured"]


def jira_get(path, params=None):
    url = f"{BASE}{path}"
    if params:
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {AUTH}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def search(jql, fields, max_results=100):
    body = json.dumps({"jql": jql, "fields": fields, "maxResults": max_results}).encode()
    req = urllib.request.Request(f"{BASE}/search", data=body, headers={
        "Authorization": f"Basic {AUTH}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def checked_values(field_value):
    if not field_value:
        return set()
    return {v["value"] for v in field_value}


def stage_cell(checked, stages):
    """Return (label, position, total, css_class) for a stage-tracked field."""
    total = len(stages)
    position = 0
    current = None
    for i, s in enumerate(stages, start=1):
        if s in checked:
            position = i
            current = s
    if position == 0:
        return "Not started", 0, total, "red"
    if position == total:
        return current, position, total, "green"
    return current, position, total, "amber"


def fetch_children(parent_key):
    data = search(
        f'parent = {parent_key} AND issuetype in ("Internet", "Sensing Fiber", "Node Hardware & Services")',
        ["summary", "issuetype", CF_INTERNET, CF_HARDWARE, CF_FIBER],
    )
    ip_checked, fiber_checked, hw_checked = set(), set(), set()
    has_ip, has_fiber, has_hw = False, False, False
    for issue in data.get("issues", []):
        itype = issue["fields"]["issuetype"]["name"]
        if itype == "Internet":
            has_ip = True
            ip_checked |= checked_values(issue["fields"].get(CF_INTERNET))
        elif itype == "Sensing Fiber":
            has_fiber = True
            fiber_checked |= checked_values(issue["fields"].get(CF_FIBER))
        elif itype == "Node Hardware & Services":
            has_hw = True
            hw_checked |= checked_values(issue["fields"].get(CF_HARDWARE))
    return {
        "ip": (ip_checked, has_ip),
        "fiber": (fiber_checked, has_fiber),
        "hw": (hw_checked, has_hw),
    }


def main():
    # Pull active (not Done, not On Hold) Node Deployment tickets for the project.
    parents = search(
        f'project = {PROJECT_KEY} AND issuetype = "Node Deployment" '
        f'AND statusCategory != Done AND status != "On Hold" ORDER BY duedate ASC',
        ["summary", "status", "duedate"],
    )

    projects = []
    for issue in parents.get("issues", []):
        key = issue["key"]
        fields = issue["fields"]
        duedate = fields.get("duedate")
        if not duedate:
            continue  # skip anything with no install date set
        status_name = fields["status"]["name"]
        children = fetch_children(key)

        ip_checked, has_ip = children["ip"]
        fiber_checked, has_fiber = children["fiber"]
        hw_checked, has_hw = children["hw"]

        ip_label, ip_pos, ip_total, ip_cls = stage_cell(ip_checked, IP_STAGES) if has_ip else ("NA", None, None, "gray")
        fiber_label, fiber_pos, fiber_total, fiber_cls = stage_cell(fiber_checked, FIBER_STAGES) if has_fiber else ("NA", None, None, "gray")
        hw_label, hw_pos, hw_total, hw_cls = stage_cell(hw_checked, HW_STAGES) if has_hw else ("NA", None, None, "gray")

        kml_checked = "KMLs Delivered" in fiber_checked
        quest_checked = "Deployment Questionnaire Completed" in hw_checked

        projects.append({
            "key": key,
            "name": fields["summary"],
            "duedate": duedate,
            "parent_status": status_name,
            "ip": {"label": ip_label, "pos": ip_pos, "total": ip_total, "cls": ip_cls},
            "fiber": {"label": fiber_label, "pos": fiber_pos, "total": fiber_total, "cls": fiber_cls},
            "kml": kml_checked if has_fiber else None,
            "quest": quest_checked if has_hw else None,
            "equipment": {"label": hw_label, "pos": hw_pos, "total": hw_total, "cls": hw_cls},
        })

    generated_at = datetime.datetime.utcnow().strftime("%b %d, %Y %H:%M UTC")

    with open(os.path.join(os.path.dirname(__file__), "..", "data.json"), "w") as f:
        json.dump({"generated_at": generated_at, "projects": projects}, f, indent=2)

    print(f"Wrote data.json with {len(projects)} active projects at {generated_at}")

    # Patch the "Last updated" stamp in index.html so a fresh page load shows it
    # even before any JS-driven re-render is wired up.
    index_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(index_path, "r") as f:
        html = f.read()
    html = re.sub(
        r'(<span id="lastUpdated">)[^<]*(</span>)',
        rf"\g<1>{generated_at}\g<2>",
        html,
    )
    with open(index_path, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
