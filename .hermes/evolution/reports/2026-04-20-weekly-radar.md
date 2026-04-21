# Hermes Evolution Radar

## New external signals
- **claude-mem**: the biggest gap vs Hermes is not more memory capture, but **memory governance**: pinned facts, forget/delete, provenance, confidence, and decay/TTL.
- **claude-mem**: another gap is **typed memory extraction** for people/projects/preferences/open threads, instead of mostly freeform durable notes plus episodic summaries.
- **Agent Skills**: strongest net-new signal is **semantic skill retrieval + lazy loading** from natural-language descriptions/examples, not just static metadata.
- **Agent Skills**: second net-new signal is **skill evals / verification artifacts** as part of skill authoring, beyond linting and chaining.
- **Archon / Multica**: strongest orchestration delta is **typed handoff contracts** between parent/child agents (declared input/output/artifact schema).
- **MarkItDown**: strongest ingest delta is a **converter/plugin registry boundary** so uncommon converters stay opt-in and separately packaged.
- **Rowboat**: branch/PR-native delegate outputs are interesting, but feel secondary until Hermes has stronger typed handoffs and status artifacts.

## Backlog coverage check
### Already covered
- **claude-mem** style capture/recall loop: A1-A6 already cover compression preservation, turn-start hooks, unified memory lifecycle, episodic summaries, automatic recall, and memory classes.
- **Agent Skills / Karpathy Skills** style repo-local workflow policy: B1-B6 already cover `.hermes.md` frontmatter, modular instruction packs, workflow metadata, chaining, linting, and workspace knowledge.
- **Skill resource bundles** are effectively already present in code (`tools/skills_tool.py` linked files for `references/`, `templates/`, `scripts/`, `assets/`), so no new backlog item is needed there.
- **MarkItDown** style document ingest and enrichment: C1-C3 already cover reusable ingest, structured attachments, and gateway-side enrichment.
- **Multica / Rowboat** visibility work: C4-C6 already cover unified status, richer todos, and cron fan-out.

### Backlog extension needed
1. **Memory governance controls**
   - Why: backlog has better storage/recall, but not explicit retention/editability/provenance controls.
   - Likely Hermes files/docs:
     - `tools/memory_tool.py`
     - `agent/memory_manager.py`
     - `agent/memory_provider.py`
     - `webapi/models/memory.py`
     - `webapi/routes/memory.py`
     - `website/docs/user-guide/features/memory.md`
     - `website/docs/developer-guide/memory-provider-plugin.md`
2. **Typed memory entities / relationships**
   - Why: backlog splits memory classes, but does not yet call out extraction of structured entities like people, projects, preferences, and ongoing threads.
   - Likely Hermes files/docs:
     - `agent/memory_manager.py`
     - `agent/memory_provider.py`
     - `tools/memory_tool.py`
     - `webapi/models/memory.py`
     - `website/docs/user-guide/features/memory.md`
3. **Semantic skill retrieval + lazy loading**
   - Why: backlog improves metadata, but not retrieval/ranking from plain-language intent and examples.
   - Likely Hermes files/docs:
     - `agent/skill_commands.py`
     - `agent/skill_utils.py`
     - `tools/skills_tool.py`
     - `scripts/build_skills_index.py`
     - `website/docs/developer-guide/creating-skills.md`
4. **Skill evals / verification artifacts**
   - Why: backlog mentions stronger authoring/linting, but not measurable skill validation.
   - Likely Hermes files/docs:
     - `tools/skill_manager_tool.py`
     - `website/docs/developer-guide/creating-skills.md`
     - `tests/tools/test_skill_manager_tool.py`
     - `tests/tools/test_skills_tool.py`
5. **Typed delegate handoff / artifact contracts**
   - Why: backlog covers visibility, but not a structured schema for child outputs, artifact paths, and handoff validation.
   - Likely Hermes files/docs:
     - `tools/delegate_tool.py`
     - `tools/todo_tool.py`
     - `gateway/status.py`
     - `gateway/run.py`
     - `website/docs/developer-guide/agent-loop.md`
     - `website/docs/developer-guide/architecture.md`
6. **Document converter/plugin registry**
   - Why: backlog covers ingest, but not an explicit opt-in plugin boundary inspired by MarkItDown’s converter packaging.
   - Likely Hermes files/docs:
     - `tools/document_ingest.py` (planned new file)
     - `gateway/run.py`
     - `gateway/platforms/base.py`
     - `website/docs/developer-guide/gateway-internals.md`

### No action
- **Karpathy Skills** mostly reinforces authoring style and coding discipline; useful as examples, not as a new platform primitive.
- **Rowboat** branch/PR-native delegation is attractive, but should wait until typed delegate outputs exist.
- **MarkItDown** breadth of supported formats mostly validates C1-C3 rather than changing direction.

## Recommended backlog changes
- Add a new **memory governance** item under Track A for retention/provenance/edit/delete controls.
- Add a new **typed memory entities** item under Track A for structured extraction and retrieval.
- Add a new **semantic skill retrieval** item under Track B.
- Add a new **skill eval / verification artifact** item under Track B.
- Add a new **typed delegate contract** item under Track C.
- Add a new **converter/plugin registry** item under Track C.

## Top 3 next actions
1. **Draft a P1 memory-governance backlog item** with concrete schema changes in `tools/memory_tool.py`, `webapi/models/memory.py`, and `webapi/routes/memory.py`.
2. **Draft a P1 semantic-skill-retrieval backlog item** targeting `agent/skill_commands.py`, `agent/skill_utils.py`, `tools/skills_tool.py`, and `scripts/build_skills_index.py`.
3. **Draft a P1 typed-delegate-contract backlog item** targeting `tools/delegate_tool.py`, `tools/todo_tool.py`, `gateway/status.py`, and `gateway/run.py`.

_Grounding note: MarkItDown signals were checked against accessible upstream metadata/docs; the other project comparisons were synthesized conservatively against the existing Hermes roadmap/backlog and current repo structure._