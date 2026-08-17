#!/usr/bin/env python3
"""
Pulls current deployment data from Jira and regenerates index.html —
both the KPI numbers and the table rows, not just a side data.json file.

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

CF_INTERNET = "customfield_10076"
CF_HARDWARE = "customfield_10490"
CF_FIBER = "customfield_10491"

IP_STAGES = ["Ordered", "IP Address Allocated", "Circuit Delivered",
             "Cross-Connect Ordered", "Cross-Connect Delivered", "Connected", "Live"]
FIBER_STAGES = ["KMLs Delivered", "Fiber Delivered", "Fiber Connected", "Validated", "Calibrated"]
HW_STAGES = ["Deployment Questionnaire Completed", "Design Completed", "BoM Quote", "Procurement",
             "Staging", "Shipping", "Received", "Installed", "Configured"]


def search(jql, fields, max_results=100):
    body = json.dumps({"jql": jql, "fields": fields, "maxResults": max_results}).encode()
    req = urllib.request.Request(f"{BASE}/search/jql", data=body, headers={
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


def stage_info(checked, stages):
    """Return (label, position, total, css_class) for a stage-tracked checklist."""
    total = len(stages)
    position, current = 0, None
    for i, s in enumerate(stages, start=1):
        if s in checked:
            position, current = i, s
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
    has_ip = has_fiber = has_hw = False
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
    return ip_checked, has_ip, fiber_checked, has_fiber, hw_checked, has_hw


def stage_cell_html(label, pos, total, cls):
    if cls == "gray":
        return '<td class="center"><span class="pill gray">NA</span></td>'
    return (f'<td class="center"><div class="stack2">'
            f'<span class="pill {cls}">{label}</span>'
            f'<span class="posnum">{pos}/{total}</span></div></td>')


def check_cell_html(value):
    if value is None:
        return '<td class="center"><span class="qmark no">-</span></td>'
    cls = "yes" if value else "no"
    sym = "check" if value else "x"
    sym_char = "\u2713" if value else "\u2715"
    return f'<td class="center"><span class="qmark {cls}">{sym_char}</span></td>'


def quarter_of(date_obj):
    if date_obj.month in (7, 8, 9):
        return "Q3"
    if date_obj.month in (10, 11, 12):
        return "Q4"
    return "OTHER"


def main():
    today = datetime.date.today()
    parents = search(
        f'project = {PROJECT_KEY} AND issuetype = "Node Deployment" '
        f'AND status in ("Staging", "Deployment") '
        f'AND duedate >= "{today.isoformat()}" '
        f'ORDER BY duedate ASC',
        ["summary", "status", "duedate"],
    )

    rows = []
    for issue in parents.get("issues", []):
        key = issue["key"]
        fields = issue["fields"]
        duedate = fields.get("duedate")
        if not duedate:
            continue
        date_obj = datetime.date.fromisoformat(duedate)

        ip_checked, has_ip, fiber_checked, has_fiber, hw_checked, has_hw = fetch_children(key)

        ip_label, ip_pos, ip_total, ip_cls = stage_info(ip_checked, IP_STAGES) if has_ip else (None, None, None, "gray")
        fiber_label, fiber_pos, fiber_total, fiber_cls = stage_info(fiber_checked, FIBER_STAGES) if has_fiber else (None, None, None, "gray")
        hw_label, hw_pos, hw_total, hw_cls = stage_info(hw_checked, HW_STAGES) if has_hw else (None, None, None, "gray")

        kml_val = ("KMLs Delivered" in fiber_checked) if has_fiber else None
        quest_val = ("Deployment Questionnaire Completed" in hw_checked) if has_hw else None

        rows.append({
            "key": key,
            "name": fields["summary"],
            "date_obj": date_obj,
            "date_label": date_obj.strftime("%b %-d"),
            "quarter": quarter_of(date_obj),
            "parent_status": fields["status"]["name"],
            "ip": (ip_label, ip_pos, ip_total, ip_cls),
            "fiber": (fiber_label, fiber_pos, fiber_total, fiber_cls),
            "kml": kml_val,
            "quest": quest_val,
            "equipment": (hw_label, hw_pos, hw_total, hw_cls),
        })

    html_parts = []
    seen_quarters = []
    for r in rows:
        if r["quarter"] not in seen_quarters:
            seen_quarters.append(r["quarter"])
            year = r["date_obj"].year
            html_parts.append(
                f'      <tr class="qdivider" data-q="{r["quarter"]}"><td colspan="7">{r["quarter"]} {year}</td></tr>\n'
            )
        html_parts.append(f'      <tr data-q="{r["quarter"]}">\n')
        html_parts.append(f'        <td class="datecell">{r["date_label"]}</td>\n')
        html_parts.append(f'        <td class="proj">{r["name"]}</td>\n')
        html_parts.append(f'        {stage_cell_html(*r["ip"])}\n')
        html_parts.append(f'        {stage_cell_html(*r["fiber"])}\n')
        html_parts.append(f'        {check_cell_html(r["kml"])}\n')
        html_parts.append(f'        {check_cell_html(r["quest"])}\n')
        html_parts.append(f'        {stage_cell_html(*r["equipment"])}\n')
        html_parts.append('      </tr>\n\n')
    rows_html = "".join(html_parts)

    today = datetime.date.today()
    next_install = min(rows, key=lambda r: r["date_obj"]) if rows else None
    within_30 = sum(1 for r in rows if 0 <= (r["date_obj"] - today).days <= 30)
    ready_install = sum(1 for r in rows if r["equipment"][3] == "green")
    ready_setup = sum(
        1 for r in rows
        if r["ip"][3] == "green" and r["fiber"][3] == "green"
        and r["kml"] is True and r["quest"] is True and r["equipment"][3] == "green"
    )

    # --- Gantt: next 3 calendar months starting from this month ---
    month_starts = []
    y, m = today.year, today.month
    for _ in range(3):
        month_starts.append(datetime.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    window_start = month_starts[0]
    next_month_start = datetime.date(
        month_starts[-1].year + (1 if month_starts[-1].month == 12 else 0),
        1 if month_starts[-1].month == 12 else month_starts[-1].month + 1,
        1,
    )
    window_days = (next_month_start - window_start).days

    def month_pct(d):
        return round((d - window_start).days / window_days * 100, 2)

    gantt_months_html = "".join(
        f'          <div class="gmonth">{d.strftime("%B %Y")}</div>\n' for d in month_starts
    )
    gridline_pcts = [month_pct(month_starts[1]), month_pct(month_starts[2])]

    gantt_rows_html = []
    for r in rows:
        if not (window_start <= r["date_obj"] < next_month_start):
            continue
        pct = month_pct(r["date_obj"])
        status = r["parent_status"]
        is_staging = status.lower() in ("staging", "to do", "backlog")
        css_cls = "staging" if is_staging else "deployment"
        flip = " flip" if pct > 85 else ""
        gantt_rows_html.append(
            '        <div class="gantt-row">\n'
            f'          <div class="gantt-rowlabel"><div class="grname">{r["name"]}</div>'
            f'<div class="grdate">{r["date_label"]}</div></div>\n'
            '          <div class="gantt-track">\n'
            f'            <div class="gantt-gridline" style="left:{gridline_pcts[0]}%"></div>\n'
            f'            <div class="gantt-gridline" style="left:{gridline_pcts[1]}%"></div>\n'
            f'            <div class="gantt-marker-wrap {css_cls}{flip}" style="left:{pct}%">'
            f'<span class="gdot"></span><span class="glabel">{status}</span></div>\n'
            '          </div>\n'
            '        </div>\n\n'
        )
    gantt_rows_html = "".join(gantt_rows_html)

    generated_at = datetime.datetime.utcnow().strftime("%b %d, %Y %H:%M UTC")

    index_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(index_path, "r") as f:
        html = f.read()

    html = re.sub(
        r'(<span id="lastUpdated">)[^<]*(</span>)',
        rf"\g<1>{generated_at}\g<2>",
        html,
    )
    html = re.sub(
        r'(<!-- ROWS:START -->\n)(.*?)(\n?\s*<!-- ROWS:END -->)',
        lambda m: m.group(1) + rows_html + m.group(3),
        html, flags=re.S,
    )
    html = re.sub(
        r'(<!-- GANTT_MONTHS:START -->\n)(.*?)(\s*<!-- GANTT_MONTHS:END -->)',
        lambda m: m.group(1) + gantt_months_html + m.group(3),
        html, flags=re.S,
    )
    html = re.sub(
        r'(<!-- GANTT_ROWS:START -->\n)(.*?)(\n?\s*<!-- GANTT_ROWS:END -->)',
        lambda m: m.group(1) + gantt_rows_html + m.group(3),
        html, flags=re.S,
    )
    if next_install:
        html = re.sub(
            r'(id="kpiNext"><div class="num">)[^<]*(</div><div class="lbl">)[^<]*(</div>)',
            rf'\g<1>{next_install["date_label"]}\g<2>Next install - {next_install["name"]}\g<3>',
            html,
        )
    html = re.sub(r'(id="kpi30d"><div class="num">)[^<]*(</div>)', rf'\g<1>{within_30}\g<2>', html)
    html = re.sub(r'(id="kpiReadyInstall"><div class="num">)[^<]*(</div>)', rf'\g<1>{ready_install}\g<2>', html)
    html = re.sub(r'(id="kpiReadySetup"><div class="num">)[^<]*(</div>)', rf'\g<1>{ready_setup}\g<2>', html)

    with open(index_path, "w") as f:
        f.write(html)

    data_path = os.path.join(os.path.dirname(__file__), "..", "data.json")
    with open(data_path, "w") as f:
        json.dump({
            "generated_at": generated_at,
            "projects": [
                {**{k: v for k, v in r.items() if k != "date_obj"}, "date": r["date_obj"].isoformat()}
                for r in rows
            ],
        }, f, indent=2, default=str)

    print(f"Updated index.html with {len(rows)} active projects - generated {generated_at}")


if __name__ == "__main__":
    main()
