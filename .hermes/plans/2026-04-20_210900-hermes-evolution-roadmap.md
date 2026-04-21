# Hermes Evolution Roadmap and Improvement Checklist

> **For Hermes:** Use `subagent-driven-development` for execution tasks that modify code. Use this document as the source of truth for evolution planning, weekly audits, and progress reporting.

**Goal:** Turn the external inspiration set into an actionable Hermes improvement program, prioritizing memory, structured skills/workflows, orchestration visibility, repo-local policy, and document ingest.

**Architecture:** Evolve Hermes in three layers: (1) runtime substrate upgrades for memory/workflows/orchestration, (2) product-facing UX and repo-local conventions, and (3) recurring research/audit loops so the roadmap keeps adapting as external projects evolve.

**Tech Stack:** Hermes Agent Python codebase, markdown roadmap/checklists, YAML backlog, cron automation.

---

## Source Project Mapping

### High priority
1. **claude-mem** → automatic capture/compression/recall, episodic memory, structured memory layers
2. **Agent Skills** → stronger skill contracts, workflow metadata, verification-oriented skill authoring
3. **Archon** → declarative/repeatable YAML workflows and repo-local structured policy
4. **Multica** → multi-agent task routing, task-board state, child-agent progress visibility

### Medium priority
5. **Andrej Karpathy Skills** → repo-local policy files, orientation checklists, durable workspace knowledge
6. **MarkItDown** → unified document ingest/markdown conversion pipeline
7. **Rowboat** → visual/run-state representation, workflow IDE concepts for future UI work

### Lower priority / later exploration
8. **DeepTutor** → domain-specific tutor mode, not core Hermes runtime work
9. **VoxCPM** → local/high-quality TTS path, useful but not central to agent evolution
10. **ChinaTextbook** → not part of core product evolution

---

# Improvement Checklist

## Track A — Memory evolution (claude-mem)

### A1. Fix compression-time memory preservation wiring
- **Priority:** P0
- **Outcome:** `on_pre_compress()` output materially influences compression summaries.
- **Likely files:**
  - `run_agent.py`
  - `agent/context_compressor.py`
- **Validation:** compression path tests prove memory hints are included in summary generation.

### A2. Wire turn-start memory hooks in the main loop
- **Priority:** P0
- **Outcome:** providers can do cadence-aware capture/recall on each turn.
- **Likely files:**
  - `run_agent.py`
  - `agent/memory_manager.py`
- **Validation:** providers receive `on_turn_start` consistently in integration tests.

### A3. Unify built-in memory behind `MemoryManager`
- **Priority:** P1
- **Outcome:** built-in and external memory share one lifecycle and one policy surface.
- **Likely files:**
  - `run_agent.py`
  - `agent/memory_manager.py`
  - `agent/memory_provider.py`
  - `tools/memory_tool.py`
- **Validation:** built-in memory writes, auto-capture, and provider callbacks all route through the same manager.

### A4. Add local episodic summaries derived from session history
- **Priority:** P1
- **Outcome:** Hermes stores compact per-session/per-compression summaries for automatic recall.
- **Likely files:**
  - `hermes_state.py`
  - `tools/session_search_tool.py`
  - `agent/context_engine.py`
- **Validation:** episodic records are created and queryable after session end/compression.

### A5. Add automatic episodic recall before relevant turns
- **Priority:** P1
- **Outcome:** Hermes recalls relevant prior work without requiring manual `session_search` first.
- **Likely files:**
  - `run_agent.py`
  - `agent/memory_manager.py`
  - `hermes_state.py`
- **Validation:** relevant prior episodes are injected when task similarity crosses threshold.

### A6. Split durable memory into structured classes
- **Priority:** P2
- **Outcome:** user facts, project conventions, episodic history, and procedural lessons have separate storage semantics.
- **Likely files:**
  - `tools/memory_tool.py`
  - `agent/memory_provider.py`
  - `webapi/routes/memory.py`
- **Validation:** new schema remains backwards-compatible with current MEMORY/USER views.

## Track B — Skills, workflows, and repo policy (Agent Skills + Archon + Karpathy)

### B1. Parse structured frontmatter in `.hermes.md`
- **Priority:** P0
- **Outcome:** repo-local files can declare preferred skills, verification steps, and workflow presets.
- **Likely files:**
  - `agent/prompt_builder.py`
  - `agent/context_references.py`
- **Validation:** frontmatter fields are loaded and honored in prompt assembly.

### B2. Add declarative workflow metadata to skills
- **Priority:** P1
- **Outcome:** skills expose triggers, workflow steps, deliverables, review loops, and handoffs as machine-readable metadata.
- **Likely files:**
  - `agent/skill_utils.py`
  - `tools/skills_tool.py`
  - `tools/skill_manager_tool.py`
- **Validation:** `skill_view()` returns structured workflow metadata and authoring docs describe the schema.

### B3. Support modular repo-local instruction packs
- **Priority:** P1
- **Outcome:** `.hermes/rules/`, `.hermes/workflows/`, and similar folders layer instructions cleanly.
- **Likely files:**
  - `agent/subdirectory_hints.py`
  - `agent/prompt_builder.py`
- **Validation:** directory-scoped policy/workflow modules are discovered progressively without blowing up prompt size.

### B4. Turn `related_skills` into operational chaining
- **Priority:** P2
- **Outcome:** skills can recommend or auto-load adjacent workflow skills.
- **Likely files:**
  - `agent/skill_commands.py`
  - `tools/skills_tool.py`
- **Validation:** plan → execution → review chains become discoverable and testable.

### B5. Enforce a stronger skill authoring/linting contract
- **Priority:** P2
- **Outcome:** new skills consistently include triggers, procedure, pitfalls, verification, and examples.
- **Likely files:**
  - `tools/skill_manager_tool.py`
  - `website/docs/developer-guide/creating-skills.md`
- **Validation:** skill creation/patch paths lint or scaffold required sections.

### B6. Add a first-class workspace knowledge-base primitive
- **Priority:** P2
- **Outcome:** Hermes can maintain a repo-local knowledge file/index for accumulated project understanding.
- **Likely files:**
  - `agent/context_references.py`
  - `agent/prompt_builder.py`
  - optional docs/skill integration with `llm-wiki`
- **Validation:** workspace knowledge artifacts are easy to update and reference.

## Track C — Orchestration visibility and document ingest (Multica + Rowboat + MarkItDown)

### C1. Build a reusable document-ingest module
- **Priority:** P1
- **Outcome:** Hermes can convert PDF/DOCX/XLSX/PPTX and similar assets into markdown/text artifacts.
- **Likely files:**
  - `tools/document_ingest.py` (new)
  - `gateway/run.py`
- **Validation:** attachments produce structured markdown/text outputs with metadata.

### C2. Upgrade attachment handling to structured objects
- **Priority:** P1
- **Outcome:** attachments preserve filename, MIME, local path, parsed artifacts, and summaries.
- **Likely files:**
  - `gateway/platforms/base.py`
  - platform adapters in `gateway/platforms/`
- **Validation:** all supported platforms emit normalized attachment records.

### C3. Add gateway-side document enrichment
- **Priority:** P1
- **Outcome:** documents arrive with parsed summaries similar to how images/audio already get vision/transcription enrichment.
- **Likely files:**
  - `gateway/run.py`
- **Validation:** prompt context for document messages includes concise summaries + artifact paths.

### C4. Create a unified task/run status surface
- **Priority:** P1
- **Outcome:** `/status` can show parent task, child delegates, todos, and cron state in one view.
- **Likely files:**
  - `gateway/run.py`
  - `run_agent.py`
  - `tools/todo_tool.py`
  - `tools/delegate_tool.py`
- **Validation:** delegated work and checklist state become inspectable during execution.

### C5. Extend todo items with orchestration metadata
- **Priority:** P2
- **Outcome:** todo items can track owner, dependencies, artifact paths, run IDs, and priority.
- **Likely files:**
  - `tools/todo_tool.py`
- **Validation:** parent/child task graphs are representable and stable across updates.

### C6. Add cron fan-out / delegated execution mode
- **Priority:** P2
- **Outcome:** scheduled jobs can run multi-agent workstreams and aggregate the result.
- **Likely files:**
  - `cron/scheduler.py`
  - `tools/cronjob_tools.py`
- **Validation:** a cron job can launch parallel subtasks and return a merged report.

---

# Phase Plan

## Phase 1 — Foundation (next 1–2 implementation cycles)
- A1, A2
- B1
- C1, C2, C3

## Phase 2 — Structured evolution (next 2–4 cycles)
- A3, A4, A5
- B2, B3
- C4

## Phase 3 — Operational maturity (later)
- A6
- B4, B5, B6
- C5, C6

---

# Evolution Task Deployment Rules

1. Weekly research/audit must revisit the high- and medium-priority source projects only.
2. Any proposed roadmap change must name exact Hermes files or docs likely to change.
3. Reports must separate:
   - newly observed external ideas
   - already-covered roadmap items
   - implementation-ready next steps
4. If a roadmap item appears completed in the codebase, mark it as done and identify remaining gaps.
5. Do not auto-edit code in cron jobs; generate reports, diffs-to-consider, and prioritized next actions.

---

# Deliverables to Maintain
- `.hermes/plans/2026-04-20_210900-hermes-evolution-roadmap.md`
- `.hermes/evolution/hermes-evolution-backlog.yaml`
- `.hermes/evolution/reports/` (cron-delivered reports or saved outputs)
- cron jobs for radar, audit, and execution planning

---

# Success Criteria
- Hermes has a living backlog mapped to concrete files and phased priorities.
- There are recurring jobs that keep the roadmap fresh and track upstream inspiration.
- The next implementation session can pick a P0/P1 task without redoing discovery work.
