# Q3/Q4 Deployments Dashboard

Executive view of current Jira deployments (IP / Fiber / KML / Questionnaire / Equipment
readiness), auto-refreshed daily from Jira and viewable by anyone with the link.

## 1. Create the repo

1. Go to https://github.com/new
2. Name it something like `deployment-dashboard` (Private is fine — Pages can still
   be shared via a direct link, or make it Public if you want zero friction).
3. Upload these files keeping the same folder structure:
   ```
   index.html
   data.json                 (created automatically on first run)
   scripts/generate_dashboard.py
   .github/workflows/update-dashboard.yml
   README.md
   ```

## 2. Add your Jira credentials as repo secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**
and add three secrets:

| Secret name       | Value                                            |
|--------------------|---------------------------------------------------|
| `JIRA_DOMAIN`      | `fibersense.atlassian.net` (no `https://`)         |
| `JIRA_EMAIL`       | the email of the Jira account used for API access  |
| `JIRA_API_TOKEN`   | an API token — create one at https://id.atlassian.com/manage-profile/security/api-tokens |

These secrets are only ever used inside GitHub's own servers when the workflow
runs — they are never exposed to anyone viewing the published page.

## 3. Turn on GitHub Pages

**Settings → Pages → Build and deployment → Source: Deploy from a branch →
Branch: `main` / `(root)` → Save.**

GitHub will give you a URL like:
`https://<your-username>.github.io/deployment-dashboard/`

Share that link with Rachel, Carolina, or anyone else who needs to see it —
they don't need a GitHub account to view it.

## 4. How the auto-refresh works

- `.github/workflows/update-dashboard.yml` runs every day at **06:00 UTC**
  (edit the `cron:` line in that file to change the time).
- It calls `scripts/generate_dashboard.py`, which queries Jira for all
  active Node Deployment tickets in the `SDO` project, pulls their IP /
  Fiber / Equipment checklists, and rewrites `data.json` + the
  "Last updated" stamp in `index.html`.
- It then commits and pushes the change automatically. GitHub Pages
  picks up the new `index.html` within a minute or two.

## 5. Manual refresh (whenever you need it)

Go to the **Actions** tab → **Update Deployment Dashboard** (left sidebar) →
**Run workflow** button (top right) → **Run workflow**.

That's the one-click manual control — no need to wait for the daily schedule.

## Notes / limitations

- Only tickets with a **Due Date** set are included — anything without one
  is skipped, since there's nothing to plot on the calendar.
- Tickets with status `On Hold` are excluded automatically.
- **Everything on the page is now regenerated every run**: the table
  (dates, IP/Fiber/KML/Questionnaire/Equipment), the 4 KPI numbers, the
  Timeline/Gantt view (month columns roll forward automatically to
  always show "today's month + the next 2"), and the "Last updated"
  stamp. Nothing on the page is hand-edited anymore.
- The Gantt marker color reflects the **parent ticket's own status**
  in Jira (`Staging` = amber, anything else active = green) — same rule
  used throughout this dashboard.
