# Skill Analytics + Dashboard Integration Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Add first-class skill analytics to Hermes, including durable event tracking, queryable per-skill metrics, and integration into the existing Web Dashboard analytics + skills surfaces.

Architecture: Introduce a new `skill_events` event table and a small analytics layer in `hermes_state.py` so skill activity becomes a first-class observable stream like sessions and tool calls. Instrument all meaningful skill lifecycle entry points (`skill_view`, slash-command invocation, preloaded skills, related-skill chaining, enable/disable/install/update/delete when available), then expose aggregates through new FastAPI endpoints consumed by the existing React dashboard. Reuse the current Web UI structure by extending both the Analytics page and Skills page rather than creating a separate app.

Tech Stack: SQLite (existing `state.db`), FastAPI (`hermes_cli/web_server.py`), React + Vite (`web/src`), existing session/skills infrastructure in `tools/skills_tool.py`, `agent/skill_commands.py`, and `hermes_state.py`.

---

## Current Context / Findings

Observed existing integration points in this repo:

- Database schema lives in `hermes_state.py`; current `SCHEMA_VERSION = 7`.
- The web dashboard already exists and is documented in `website/docs/user-guide/features/web-dashboard.md`.
- The FastAPI backend for the dashboard is in `hermes_cli/web_server.py`.
- Existing dashboard pages:
  - `web/src/pages/AnalyticsPage.tsx`
  - `web/src/pages/SkillsPage.tsx`
  - navigation in `web/src/App.tsx`
- Current dashboard APIs already include:
  - `GET /api/skills`
  - `PUT /api/skills/toggle`
  - `GET /api/analytics/usage`
- Current skill loading paths:
  - `tools/skills_tool.py` → `skills_list()`, `skill_view()`, `_find_all_skills()`
  - `agent/skill_commands.py` → `build_skill_invocation_message()`, `build_preloaded_skills_prompt()`, related-skill chaining
- Current analytics do not track skills; they only track sessions/tokens/costs.

Design principle for this feature: a skill should stop being “just prompt text” and become an observable asset with lifecycle, usage, and quality metrics.

---

## Scope

This plan covers an MVP+ implementation with:

1. Durable skill event logging
2. Aggregated skill analytics API
3. Skill analytics panels in the existing dashboard
4. Better metadata on the Skills page
5. Tests for schema migration, logging, API responses, and UI behavior

This plan intentionally does not include:

- ML-based skill recommendation/ranking
- graph visualization libraries
- cross-profile analytics federation
- retroactive perfect backfill of all historical skill usage

Historical backfill should be heuristic and optional, not required for correctness.

---

## Data Model

### New table: `skill_events`

Add to `~/.hermes/state.db` via `hermes_state.py` migration.

Recommended schema:

```sql
CREATE TABLE IF NOT EXISTS skill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    timestamp REAL NOT NULL,
    source TEXT,
    skill_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    trigger TEXT,
    parent_skill_name TEXT,
    success INTEGER,
    metadata_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_skill_events_skill_time
    ON skill_events(skill_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_skill_events_session
    ON skill_events(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_skill_events_type_time
    ON skill_events(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_skill_events_source_time
    ON skill_events(source, timestamp DESC);
```

### Event taxonomy

Use a constrained event vocabulary from day one:

- `viewed` — user/tool loaded a skill via `skill_view`
- `invoked` — user invoked a skill command directly
- `preloaded` — session launched with `--skills`
- `chained` — related skill auto-loaded from another skill
- `enabled`
- `disabled`
- `installed`
- `updated`
- `deleted`

Triggers:

- `tool_call`
- `slash_command`
- `preload_flag`
- `auto_chain`
- `web_dashboard`
- `skills_hub`
- `cli`

### Why event log first, not only aggregates

Event log gives:
- auditability
- future aggregation flexibility
- dashboard trendlines without schema churn
- optional future exports/CSV

Do not start with only cached aggregates; derive aggregates from the event log for MVP.

---

## Metrics to compute

### Core per-skill metrics

For each skill over a selected period:

- total_events
- view_count
- invoke_count
- preload_count
- chained_count
- unique_sessions
- last_used_at
- first_seen_at
- primary_source_counts
- enabled (from current config, not event history)
- category
- description

### Dashboard summary metrics

- active_skills_in_period
- total_skill_invocations
- total_skill_views
- total_preloads
- total_chained_loads
- unique_skills_used
- unused_skill_count
- top_skills
- top_categories
- daily_skill_activity

### Nice-to-have but still feasible in MVP

- `adoption_rate = unique_skills_used / total_installed_skills`
- `invoke_to_view_ratio`
- `chain_ratio = chained_count / max(invoke_count, 1)`

Avoid subjective “quality score” in v1. It creates debate before the raw observability exists.

---

## API Design

Extend the existing dashboard backend in `hermes_cli/web_server.py`.

### 1. GET `/api/analytics/skills?days=30`

Purpose: aggregate skill activity for the Analytics page.

Response shape:

```json
{
  "period_days": 30,
  "totals": {
    "total_events": 0,
    "total_views": 0,
    "total_invocations": 0,
    "total_preloads": 0,
    "total_chained": 0,
    "unique_skills_used": 0,
    "active_skill_count": 0,
    "installed_skill_count": 0,
    "unused_skill_count": 0
  },
  "daily": [
    {
      "day": "2026-04-21",
      "views": 0,
      "invocations": 0,
      "preloads": 0,
      "chained": 0,
      "unique_skills": 0
    }
  ],
  "top_skills": [
    {
      "skill_name": "plan",
      "category": "software-development",
      "views": 4,
      "invocations": 2,
      "preloads": 0,
      "chained": 0,
      "unique_sessions": 2,
      "last_used_at": 1770000000.0
    }
  ],
  "top_categories": [
    {
      "category": "software-development",
      "events": 10,
      "unique_skills": 3
    }
  ]
}
```

### 2. GET `/api/skills/stats`

Purpose: enrich the Skills page with per-skill counters.

Query params:
- `days` default 30
- optional `limit`

Response shape:

```json
{
  "period_days": 30,
  "skills": [
    {
      "name": "plan",
      "description": "...",
      "category": "software-development",
      "enabled": true,
      "views": 4,
      "invocations": 2,
      "preloads": 0,
      "chained": 0,
      "unique_sessions": 2,
      "last_used_at": 1770000000.0,
      "first_seen_at": 1769990000.0
    }
  ]
}
```

### 3. Optional follow-up endpoint: GET `/api/skills/{name}/stats?days=30`

Not required in the first UI pass, but useful if you later want a drawer/modal on the Skills page.

---

## Backend implementation plan

### Task 1: Add schema migration for `skill_events`

Objective: make skill analytics durable in the existing SQLite state store.

Files:
- Modify: `hermes_state.py`
- Test: `tests/hermes_state` (create new test file if needed, likely `tests/test_hermes_state_skill_events.py`)

Steps:
1. Bump `SCHEMA_VERSION` from `7` to `8` in `hermes_state.py`.
2. Add `skill_events` CREATE TABLE + indexes to `SCHEMA_SQL` or migration block.
3. Add a `current_version < 8` migration block in `_init_schema()`.
4. Ensure migration is idempotent.
5. Add tests proving:
   - fresh DB gets the table
   - migrated DB from prior schema gets the table
   - rerunning init does not fail

Verification:
- `python -m pytest tests/ -o 'addopts=' -q -k skill_events`

### Task 2: Add a small skill-event logging API to `SessionDB`

Objective: give the rest of the app one obvious way to emit skill analytics events.

Files:
- Modify: `hermes_state.py`
- Test: `tests/test_hermes_state_skill_events.py`

Add methods like:

```python
def log_skill_event(
    self,
    *,
    skill_name: str,
    event_type: str,
    session_id: str | None = None,
    source: str | None = None,
    trigger: str | None = None,
    parent_skill_name: str | None = None,
    success: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> None: ...
```

and read methods like:

```python
def get_skill_analytics(self, days: int = 30) -> dict[str, Any]: ...
def get_skill_stats(self, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]: ...
```

Implementation guidance:
- store `metadata_json` as compact JSON
- serialize booleans to nullable integer 0/1
- use SQL aggregation for counts and daily rollups
- keep all query code inside `SessionDB` so the web server stays thin

Verification:
- unit tests for inserts
- unit tests for aggregation output shapes
- unit tests for empty-db behavior

### Task 3: Instrument `skill_view()` as `viewed`

Objective: log explicit skill inspections via the tool.

Files:
- Modify: `tools/skills_tool.py`
- Test: `tests/tools/test_skills_tool.py`

Rules:
- only log after successful resolution of a skill
- `event_type = viewed`
- `trigger = tool_call`
- `session_id` should be attached if available from current task/session context; if unavailable, allow null
- if `file_path` is present, include it in `metadata_json`

Pitfall:
- `skill_view()` may be used to read a reference file inside a skill. That should still count as a view of the owning skill, but mark the subpath in metadata.

Verification:
- add a test that monkeypatches/log-spies and confirms a successful `skill_view()` emits exactly one event
- add a test that failed lookup emits none

### Task 4: Instrument skill invocation and preloading

Objective: track real skill usage, not just inspection.

Files:
- Modify: `agent/skill_commands.py`
- Test: likely new file `tests/agent/test_skill_commands_analytics.py`

Instrumentation points:

1. `build_skill_invocation_message()`
- root skill → `event_type = invoked`, `trigger = slash_command`
- chained related skills → `event_type = chained`, `trigger = auto_chain`, `parent_skill_name = <root skill>`

2. `build_preloaded_skills_prompt()`
- root preloaded skill → `event_type = preloaded`, `trigger = preload_flag`
- related skills loaded from preloaded skill → `event_type = chained`, `trigger = auto_chain`

Important:
- do not double-count the root skill in a single invocation path
- each chained skill may emit once per load event
- preserve existing behavior; logging must be side-effect-light and never block prompt construction

Verification:
- test direct invocation logs invoked + chained as expected
- test preloading logs preloaded + chained
- test missing skill does not log false positives

### Task 5: Instrument skill enable/disable in CLI + dashboard backend

Objective: track operational skill management, not only runtime usage.

Files:
- Modify: `hermes_cli/skills_config.py`
- Modify: `hermes_cli/web_server.py`
- Test: `tests/hermes_cli/test_web_server.py`

Rules:
- when saving skill state changes, log `enabled` or `disabled`
- dashboard toggles should include `trigger = web_dashboard`
- CLI toggles should include `trigger = cli`

Implementation note:
- if the current helper only persists sets in bulk, compute set differences before/after save so you can emit one event per changed skill

Verification:
- toggling one skill through `/api/skills/toggle` produces the expected event
- no event when requested state already matches stored state

### Task 6: Add web API endpoints for skill analytics

Objective: expose the data to the dashboard in a way consistent with existing usage analytics.

Files:
- Modify: `hermes_cli/web_server.py`
- Test: `tests/hermes_cli/test_web_server.py`

Add endpoints:
- `GET /api/analytics/skills`
- `GET /api/skills/stats`

Implementation guidance:
- instantiate `SessionDB()` in each handler just like `/api/analytics/usage`
- return empty but valid payloads for no-data cases
- enrich `skills/stats` by joining current skill inventory from `_find_all_skills(skip_disabled=True)` plus current enabled status from config
- include installed-but-never-used skills with zero counts so the dashboard can highlight them

Verification:
- endpoint returns 200 with well-formed empty response on fresh DB
- endpoint returns non-empty aggregates when seeded with events
- response includes enabled state and category metadata

### Task 7: Extend the shared frontend API types

Objective: make the React frontend aware of skill analytics responses.

Files:
- Modify: `web/src/lib/api.ts`

Add:
- `api.getSkillAnalytics(days)`
- `api.getSkillStats(days)`
- TypeScript interfaces for:
  - `SkillAnalyticsResponse`
  - `SkillAnalyticsDailyEntry`
  - `SkillAnalyticsTopSkill`
  - `SkillStatsResponse`
  - richer `SkillInfo` / `SkillStatInfo` as needed

Keep `getSkills()` unchanged if you want backwards compatibility; add a dedicated richer endpoint wrapper for stats.

Verification:
- `cd web && npm run build`

### Task 8: Add skill analytics cards to Analytics page

Objective: integrate skill usage into the existing Analytics dashboard page.

Files:
- Modify: `web/src/pages/AnalyticsPage.tsx`

Approach:
- load both usage analytics and skill analytics in the same page
- add a second section below the token/cost analytics called “Skill Analytics”
- add summary cards for:
  - active skills
  - total invocations
  - total views
  - total preloads
- add a daily chart or compact stacked bar for views/invocations/preloads/chained
- add tables for:
  - top skills
  - top categories

Keep the visual system consistent with the existing page:
- same `Card` components
- same period selector (7/30/90 days)
- same muted palette and compact tables

Verification:
- `cd web && npm run build`
- manual browser check with `hermes web`

### Task 9: Upgrade the Skills page from inventory to management surface

Objective: make the Skills page show value, not only toggles.

Files:
- Modify: `web/src/pages/SkillsPage.tsx`

Add columns/metadata per skill:
- enabled/disabled toggle (existing)
- views
- invocations
- preloads
- unique sessions
- last used

Recommended UX:
- retain current grouped-by-category layout
- add sort/filter options:
  - most used
  - recently used
  - unused
  - enabled only
  - disabled only
- show a small summary banner at top:
  - installed skills
  - active in period
  - never used
- optionally add an “Unused” badge to zero-usage skills

Do not overbuild in v1:
- no modal detail pages unless the core data is working
- no graph view yet

Verification:
- `cd web && npm run build`
- manual browser test toggling filters/search

### Task 10: Add backend and UI docs

Objective: document the feature so users understand where the numbers come from.

Files:
- Modify: `website/docs/user-guide/features/web-dashboard.md`
- Optionally modify: docs describing `hermes insights` and skills behavior if needed

Doc updates:
- explain that skill analytics are now first-class
- document new dashboard sections/endpoints
- explain what counts as a view vs invocation vs preload vs chained load
- mention that historical data begins when this feature is installed unless a later backfill tool is added

Verification:
- doc text matches actual endpoint names and UI labels

---

## Suggested file-by-file change list

Backend core:
- `hermes_state.py`
- `tools/skills_tool.py`
- `agent/skill_commands.py`
- `hermes_cli/skills_config.py`
- `hermes_cli/web_server.py`

Frontend:
- `web/src/lib/api.ts`
- `web/src/pages/AnalyticsPage.tsx`
- `web/src/pages/SkillsPage.tsx`
- optional small shared component if repetition gets high, e.g. `web/src/components/SkillUsageTable.tsx`

Tests:
- `tests/hermes_cli/test_web_server.py`
- `tests/tools/test_skills_tool.py`
- new: `tests/test_hermes_state_skill_events.py`
- new: `tests/agent/test_skill_commands_analytics.py`

Docs:
- `website/docs/user-guide/features/web-dashboard.md`

---

## SQL aggregation outline

### Daily skill activity

```sql
SELECT
  date(timestamp, 'unixepoch') AS day,
  SUM(CASE WHEN event_type = 'viewed' THEN 1 ELSE 0 END) AS views,
  SUM(CASE WHEN event_type = 'invoked' THEN 1 ELSE 0 END) AS invocations,
  SUM(CASE WHEN event_type = 'preloaded' THEN 1 ELSE 0 END) AS preloads,
  SUM(CASE WHEN event_type = 'chained' THEN 1 ELSE 0 END) AS chained,
  COUNT(DISTINCT skill_name) AS unique_skills
FROM skill_events
WHERE timestamp > ?
GROUP BY day
ORDER BY day;
```

### Top skills in period

```sql
SELECT
  skill_name,
  SUM(CASE WHEN event_type = 'viewed' THEN 1 ELSE 0 END) AS views,
  SUM(CASE WHEN event_type = 'invoked' THEN 1 ELSE 0 END) AS invocations,
  SUM(CASE WHEN event_type = 'preloaded' THEN 1 ELSE 0 END) AS preloads,
  SUM(CASE WHEN event_type = 'chained' THEN 1 ELSE 0 END) AS chained,
  COUNT(DISTINCT session_id) AS unique_sessions,
  MAX(timestamp) AS last_used_at,
  MIN(timestamp) AS first_seen_at
FROM skill_events
WHERE timestamp > ?
GROUP BY skill_name
ORDER BY (invocations + preloads + chained + views) DESC, last_used_at DESC;
```

Use Python post-processing to join category/description from current skill inventory.

---

## UI layout recommendation

### Analytics page

Keep existing token analytics at top. Add a clear divider and then:

1. Skill summary cards
2. Daily skill activity chart
3. Top skills table
4. Top categories table

Reason: users already think “Analytics” is the place for usage patterns.

### Skills page

Keep it as the management/inventory page, but enrich it with usage stats. This is where users answer:
- what do I have?
- what is enabled?
- what is dead weight?
- what is most valuable?

This dual placement is correct, not redundant:
- Analytics = trends and aggregate usage
- Skills = inventory and operational management

---

## Backfill strategy (optional, not blocking)

After MVP is working, add a one-shot backfill helper that mines existing `messages.content` for known skill-invocation markers from `agent/skill_commands.py`.

Do not block the MVP on this.

If implemented later:
- put it behind a CLI/admin action, not automatic migration
- mark inferred rows in `metadata_json` with `{"inferred": true, "source": "historical_message_mining"}`
- only infer `invoked` / `preloaded` when the message pattern is explicit
- do not fabricate views

---

## Risks / Pitfalls

1. Double counting
- `skill_view()` used internally vs user-initiated reads can inflate view counts.
- Mitigation: use clear trigger metadata and only log on successful operations.

2. Session context availability
- some tool calls may not easily expose `session_id`.
- Mitigation: allow nullable `session_id`; do not block logging on it.

3. Chained related skills ambiguity
- a root invocation can auto-load multiple related skills.
- Mitigation: keep `parent_skill_name` and separate `chained` event type.

4. Disabled skill inventory visibility
- some code paths use `_find_all_skills(skip_disabled=True)`; for dashboard inventory you may need to show disabled skills too.
- Mitigation: ensure the inventory endpoint can still enumerate all installed skills while separately computing enabled state.

5. UI over-complexity
- trying to add graphs, scoring, drilldowns, and cleanup tooling in one pass will bog the feature down.
- Mitigation: ship event logging + 2 endpoints + 2 page integrations first.

---

## Validation checklist

Backend:
- [ ] New DBs create `skill_events`
- [ ] Old DBs migrate cleanly to schema v8
- [ ] `skill_view()` logs `viewed`
- [ ] slash-command invocation logs `invoked`
- [ ] preloaded skills log `preloaded`
- [ ] related skills log `chained`
- [ ] dashboard/CLI toggles log enabled/disabled events
- [ ] `/api/analytics/skills` returns valid data for empty and non-empty DBs
- [ ] `/api/skills/stats` includes zero-usage installed skills

Frontend:
- [ ] `npm run build` passes
- [ ] Analytics page shows skill cards and tables
- [ ] Skills page shows per-skill usage metadata
- [ ] Period selector updates skill analytics too
- [ ] No page crashes on empty data

Docs:
- [ ] Web dashboard docs mention skill analytics
- [ ] endpoint names and semantics are documented correctly

---

## Suggested implementation order for execution

1. `hermes_state.py` migration + logging/aggregation helpers
2. instrumentation in `tools/skills_tool.py`
3. instrumentation in `agent/skill_commands.py`
4. enable/disable event logging
5. FastAPI endpoints in `hermes_cli/web_server.py`
6. TypeScript API layer in `web/src/lib/api.ts`
7. Analytics page integration
8. Skills page integration
9. tests and docs cleanup

---

## Concrete test commands

Backend focused:

```bash
cd /home/kyd/hermes-agent-enhanced
python -m pytest tests/hermes_cli/test_web_server.py -o 'addopts=' -q
python -m pytest tests/tools/test_skills_tool.py -o 'addopts=' -q
python -m pytest tests/test_hermes_state_skill_events.py -o 'addopts=' -q
python -m pytest tests/agent/test_skill_commands_analytics.py -o 'addopts=' -q
```

Frontend:

```bash
cd /home/kyd/hermes-agent-enhanced/web
npm run build
```

Optional broader verification:

```bash
cd /home/kyd/hermes-agent-enhanced
python -m pytest tests/ -o 'addopts=' -q -k 'web_server or skills or skill_events'
```

Manual verification:

```bash
cd /home/kyd/hermes-agent-enhanced
hermes web --no-open
```

Then open the dashboard and verify:
- Analytics page shows skill metrics
- Skills page shows usage counters and last-used metadata
- toggling a skill updates state and later appears in event analytics

---

## Recommendation

Implement this as an MVP in the existing dashboard, not as a separate “skills dashboard” product. The current dashboard architecture already has the right split:
- `AnalyticsPage.tsx` for time-based usage observability
- `SkillsPage.tsx` for inventory and operational management

That gives you a coherent user model with minimal product surface expansion.
