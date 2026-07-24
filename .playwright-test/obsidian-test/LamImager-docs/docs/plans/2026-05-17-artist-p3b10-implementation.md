# Artist Mode P3B-10 Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Artist the default experience layer — a person who controls image generation, not a graph node. User talks to Artist; Artist decides when to draw, asks, or discusses.

**Architecture:** Artist is an outer orchestration loop that calls LLM (PER + CON) once per round, producing both a user-facing message and an optional PLAN. If PLAN exists, a self-execution loop runs tool steps and writes results back to CON. The agent_mode_graph is simplified — Artist does not live inside it. mental-model.md's core cycle (PER + CON → LLM → PLAN → execute → CON writeback) is the architecture.

**Tech Stack:** Python 3.14+ / LangGraph (graph retained for agent fallback only) / SQLAlchemy async / Vue3

---

## Task 1: Rename persona IMAGER → AGENT

**Files:**
- `backend/app/core/persona.py`
- `backend/app/services/generate_service.py`
- `backend/app/core/mem/__init__.py`
- `backend/app/core/mem/stores.py`

**Steps:**
- [ ] Step 1: In `persona.py`, rename `IMAGER` variable to `AGENT_PERSONA`, keep name field as `"agent"`, change display_name to `"LamImager Agent"`
- [ ] Step 2: Add `IMAGER = AGENT_PERSONA` deprecated alias with comment
- [ ] Step 3: In `PERSONAS` dict, register `"agent": AGENT_PERSONA`, keep `"imager": AGENT_PERSONA` as alias
- [ ] Step 4: In `generate_service.py:790`, change default from `"imager"` to `"artist"`
- [ ] Step 5: In `generate_service.py`, change any remaining `"imager"` persona references to `"agent"`
- [ ] Step 6: In `mem/__init__.py` line 22, change default member from `"imager"` to `"artist"`
- [ ] Step 7: In `mem/stores.py` lines 53/68, change default member from `"imager"` to `"artist"`
- [ ] Step 8: In `prompt_assembler.py` line 10, change default persona_name from `"imager"` to `"artist"`

**Verification:**
- [ ] `py -3.14 -c "from app.core.persona import get_persona; print(get_persona('agent').name)"` prints `agent`
- [ ] `py -3.14 -c "from app.core.persona import get_persona; print(get_persona('imager').name)"` prints `agent` (alias)
- [ ] `py -3.14 -c "from app.core.persona import get_persona; print(get_persona('artist').name)"` prints `artist`

**Commit:** `refactor(P3): rename persona IMAGER to AGENT, default to artist`

---

## Task 2: Remove artist_dialog_node from graph

**Files:**
- `backend/app/core/agent/graph.py`
- `backend/app/core/agent/nodes/artist_dialog_node.py` (delete)

**Steps:**
- [ ] Step 1: In `graph.py`, remove `from app.core.agent.nodes.artist_dialog_node import artist_dialog_node` import
- [ ] Step 2: In `graph.py`, remove `graph.add_node("artist_dialog", artist_dialog_node)`
- [ ] Step 3: In `_after_intent`, remove the `persona == "artist"` branch that routes to `"artist_dialog"`; replace with unconditional `return "skill_matcher"`
- [ ] Step 4: Remove `_after_artist_dialog` function entirely
- [ ] Step 5: Remove `graph.add_conditional_edges("artist_dialog", ...)` line
- [ ] Step 6: Delete `backend/app/core/agent/nodes/artist_dialog_node.py`
- [ ] Step 7: In `graph_llm.py`, remove any artist_dialog_node references (if any)
- [ ] Step 8: In `frontend/src/stores/session.ts` line 15, remove `'artist_dialog'` and `'artist_thinking'` from `KEY_NODES`

**Verification:**
- [ ] `py -3.14 -m compileall backend/app/core/agent/graph.py` succeeds
- [ ] `grep -r "artist_dialog_node" backend/app/` returns no matches
- [ ] `grep -r "artist_dialog_node\|artist_dialog" frontend/src/` returns no matches in KEY_NODES

**Commit:** `refactor(P3): remove artist_dialog_node from graph`

---

## Task 3: Create Artist orchestrator

**Files:**
- `backend/app/services/artist_service.py` (new)

**Steps:**
- [ ] Step 1: Create `backend/app/services/artist_service.py`
- [ ] Step 2: Define `ARTIST_ROUND_SYSTEM` — a system prompt template that takes PER block + CON block and instructs the LLM to output JSON with `message` and optional `plan`
- [ ] Step 3: Implement `artist_orchestrate()` function:
  ```python
  async def artist_orchestrate(
      db, session_id, prompt, persona_name, llm_provider_id,
      reference_images, context_images, history_messages, task_manager
  ) -> dict:
      # 1. Read CON via MEMModule(member="artist")
      # 2. Assemble PER + Skill + CON → system prompt via PromptAssembler
      # 3. Build messages: system + history[-10:] + user input
      # 4. Call LLM, parse JSON output: { message, plan }
      # 5. If plan exists → execute steps via self-execution loop
      # 6. Write results to CON
      # 7. Return { message, artifacts }
  ```
- [ ] Step 4: Define output schema — LLM returns:
  ```json
  {
    "message": "对用户说的话",
    "plan": {
      "steps": [
        {"tool": "generate_image", "params": {"prompt": "...", "n": 1, "size": "1024x1024", "reference_images": []}}
      ]
    }
  }
  ```
  Or `"plan": null` for chat-only rounds.
- [ ] Step 5: Parse LLM output as JSON; fallback to treating raw text as `message` with no plan if JSON parse fails
- [ ] Step 6: Implement self-execution loop:
  ```python
  for step in plan.steps:
      tool_fn = TOOLS[step.tool]
      result = await tool_fn(step.params)
      artifacts.append(result)
  ```
- [ ] Step 7: After execution, call MEM write: output_index, preferences update

**Verification:**
- [ ] `py -3.14 -m compileall backend/app/services/artist_service.py` succeeds
- [ ] Import test: `py -3.14 -c "from app.services.artist_service import artist_orchestrate"` succeeds

**Commit:** `feat(P3B-10): add Artist orchestrator with PER+CON→LLM→PLAN loop`

---

## Task 4: Define Artist PER system prompt

**Files:**
- `backend/app/core/persona_artist.py`

**Steps:**
- [ ] Step 1: Rewrite `persona_artist.py` with the actual Artist system prompt block (currently placeholder)
- [ ] Step 2: Define `ARTIST_SYSTEM`:
  ```
  You are LamArtist. 19. Failed art school in Paris. You don't talk like a consultant or a poet.
  
  How you talk:
  - Speak like a real person. Short, direct, casual. Usually under 25 characters per sentence.
  - Don't force poetic language. Use it only when the image naturally calls for it.
  - Never use customer-service tone (no "好的呢", "~", "请稍等").
  - Never give menus, numbered lists, bullet points, or markdown headings.
  
  When to draw:
  - User described subject + style/direction → you can draw.
  - Vague request ("画一个好看的") → ask one clarifying question, keep it short.
  - User says "别问/直接做/直接出" → draw immediately, no questions.
  
  When not to draw:
  - User wants to discuss, brainstorm, or compare styles first.
  - You're unsure and ONE question would clear it up.
  
  Output format:
  - Always output JSON: {"message": "...", "plan": null or {...}}
  - message: what you say to the user
  - plan: if you decide to draw, include tool steps; otherwise null
  ```
- [ ] Step 3: Remove old circular import structure; this file should contain only the ARTIST_SYSTEM string

**Verification:**
- [ ] `py -3.14 -c "from app.core.persona_artist import ARTIST_SYSTEM; assert len(ARTIST_SYSTEM) > 100"` succeeds
- [ ] No circular import

**Commit:** `feat(P3B-10): define Artist PER system prompt`

---

## Task 5: Wire Artist into generate_service

**Files:**
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: In `handle_agent_generate()`, when `persona_name == "artist"`, route to `artist_orchestrate()` instead of `_run_agent_mode_graph()`
- [ ] Step 2: When `persona_name == "agent"`, keep existing `_run_agent_mode_graph()` path
- [ ] Step 3: Handle Artist orchestrator return — extract message text, broadcast to SSE, add to session messages
- [ ] Step 4: If Artist returned artifacts (images), add them to session messages with appropriate metadata
- [ ] Step 5: Ensure `data.agent_persona` defaults to `"artist"` when `data.agent_mode == True`

**Verification:**
- [ ] `py -3.14 -m compileall backend/app/services/generate_service.py` succeeds
- [ ] Logic flow: agent_mode + agent_persona="artist" → artist_orchestrate; agent_mode + agent_persona="agent" → _run_agent_mode_graph

**Commit:** `feat(P3B-10): wire Artist orchestrator into generate_service`

---

## Task 6: Write output_index after generation

**Files:**
- `backend/app/core/mem/writer.py`

**Steps:**
- [ ] Step 1: Add `write_output_entry()` function in `writer.py`:
  ```python
  def write_output_entry(member, entry: dict) -> None:
      cold_con = read_cold_con(member)
      cold_con.output_index.append(entry)
      write_cold_con(cold_con, member)
  ```
- [ ] Step 2: `entry` dict fields: `image_id`, `artifact_url`, `session_id`, `created_at`, `prompt_hash`, `role`, `style_tags`, `visual_summary` (optional), `user_feedback` (optional)
- [ ] Step 3: Call `write_output_entry` from artist orchestrator after each generation step completes
- [ ] Step 4: Trim output_index to max 100 entries, drop oldest

**Verification:**
- [ ] `py -3.14 -m compileall backend/app/core/mem/writer.py` succeeds
- [ ] Unit test: write entry → read cold con → entry exists in output_index

**Commit:** `feat(P3B-10): write output_index after image generation`

---

## Task 7: Vision review for generated images

**Files:**
- `backend/app/services/artist_service.py`

**Steps:**
- [ ] Step 1: After executor returns artifacts, if vision-capable LLM is available, call it to review generated images
- [ ] Step 2: Vision review prompt: "Describe this image briefly. Focus on subject, style, color, composition. Note any obvious issues."
- [ ] Step 3: Parse review result into `visual_summary` (1-2 sentences), `style_tags`, `issues`
- [ ] Step 4: If no vision model available, set `visual_summary` to None and mark Artist response as metadata-based
- [ ] Step 5: Feed `visual_summary` into the next Artist LLM round (so Artist can say "图3构图最稳")  
- [ ] Step 6: Write `visual_summary` into output_index

**Verification:**
- [ ] Artist can generate an image, call vision review, and produce an aesthetic comment based on actual image content
- [ ] When vision model unavailable, Artist falls back gracefully (no crash, warns in log)

**Commit:** `feat(P3B-10): add vision review for generated images`

---

## Task 8: Frontend message bubble splitting

**Files:**
- `frontend/src/stores/session.ts`

**Steps:**
- [ ] Step 1: Add helper function `splitArtistMessage(text: string): string[]` that splits by Chinese/English sentence-ending punctuation: `。！？!?` followed by optional newline
- [ ] Step 2: Each fragment becomes a separate bubble in the message list
- [ ] Step 3: Adjacent bubbles share the same `message_id` parent for grouping
- [ ] Step 4: Short fragments (< 4 chars) are merged into preceding bubble
- [ ] Step 5: SSE `artist_token` events are buffered; only split into bubbles when sentence-ending punctuation appears

**Verification:**
- [ ] "出了。图3我最喜欢。这张呢？" → 3 bubbles
- [ ] "可以。你想画人、场景，还是一张海报？" → 2 bubbles  
- [ ] "行，直接跑。" → 1 bubble

**Commit:** `feat(P3B-10): split Artist messages into sentence bubbles`

---

## Task 9: Frontend Artist toggle as default

**Files:**
- `frontend/src/views/Sessions.vue`
- `frontend/src/components/session/ComposerControls.vue`

**Steps:**
- [ ] Step 1: Set `artistMode` to `true` by default on page load
- [ ] Step 2: In `ComposerControls.vue`, reorder buttons: Artist first (default highlighted), Agent second
- [ ] Step 3: When `artistMode` is true, send `agent_mode: true, agent_persona: "artist"`
- [ ] Step 4: When `agentMode` is true, send `agent_mode: true, agent_persona: "agent"`  
- [ ] Step 5: Artist and Agent are mutually exclusive toggles
- [ ] Step 6: Change `generatingText` for Artist: `"Artist 创作中..."`

**Verification:**
- [ ] Page loads with Artist toggle active by default
- [ ] Clicking Agent deselects Artist, clicking Artist deselects Agent
- [ ] Sending a message while Artist active → request body includes `agent_persona: "artist"`

**Commit:** `feat(P3B-10): make Artist the default frontend mode`

---

## Task 10: Test Artist orchestration loop

**Files:**
- `backend/tests/test_artist_orchestrate.py` (new)

**Steps:**
- [ ] Step 1: Create test file with fixtures: mock LLM that returns `{"message": "冷蓝调我记得。我先试一张。", "plan": {"steps": [{"tool": "generate_image", "params": {"prompt": "cat", "n": 1}}]}}`
- [ ] Step 2: Test: Artist generates image → plan steps execute → output_index written
- [ ] Step 3: Test: Vague input ("画一个好看的") → Artist returns message with clarifying question, plan is null, no image generated
- [ ] Step 4: Test: User says "别问，直接出6张" → Artist plan includes `generate_image(n=6)`, no clarifying message
- [ ] Step 5: Test: Discussion mode ("你觉得赛博朋克风格现在怎么样") → message with discussion, plan is null
- [ ] Step 6: Test: CON recall works → Artist reads user preference from Cold CON and includes in prompt

**Verification:**
- [ ] `pytest backend/tests/test_artist_orchestrate.py -v` — all tests pass

**Commit:** `test(P3B-10): add Artist orchestration loop tests`

---

## Task 11: Update documentation

**Files:**
- `docs/ROADMAP.md`
- `docs/plans/PLAN.md`
- `docs/plans/2026-05-14-artist-mode-design.md`

**Steps:**
- [ ] Step 1: In `ROADMAP.md`, update P3B-10 checkboxes: mark implementation tasks complete
- [ ] Step 2: Add note that Artist is now default, agent_mode_graph is simplified
- [ ] Step 3: In `PLAN.md`, update P3B-10 description to reflect new architecture
- [ ] Step 4: In `2026-05-14-artist-mode-design.md`, add "Implementation Status" section summarizing what was built

**Verification:**
- [ ] All three documents are internally consistent
- [ ] No contradiction with mental-model.md

**Commit:** `docs(P3): update P3B-10 Artist implementation status`

---

## Dependency Order

```
Task 1 (rename) → Task 2 (remove node) → Task 3 (orchestrator) → Task 4 (PER prompt)
                                               ↓
                                          Task 5 (wire service)
                                               ↓
                                   Task 6 (output_index) + Task 7 (vision review)
                                               ↓
                              Task 8 (bubble split) + Task 9 (frontend toggle)
                                               ↓
                                          Task 10 (tests)
                                               ↓
                                          Task 11 (docs)
```

Tasks 8 and 9 can run in parallel with Tasks 6 and 7.

## Key Design Decisions

1. **Artist is NOT in the graph.** graph.py's artist_dialog_node is deleted. Artist is an outer loop that calls LLM directly.

2. **PER + CON → LLM → PLAN.** mental-model.md's core cycle. A single LLM call produces both message (user-facing text) and plan (optional execution steps).

3. **Agent is retained but relegated.** `agent_mode_graph` stays for `persona_name="agent"`. Artist doesn't use it.

4. **CON writes happen after execution.** output_index, preferences, visual_summary all written by the orchestrator, not by graph nodes.

5. **Vision review is best-effort.** If no vision model, Artist still works but cannot make strong aesthetic claims ("图3最好") without user feedback.

6. **No separate checkpoint mechanism.** "大概这个方向？" is just a message. Next user reply is the next round. No interrupt/resume.

7. **Persona naming: "artist" (default), "agent" (direct), "imager" (deprecated alias).**
