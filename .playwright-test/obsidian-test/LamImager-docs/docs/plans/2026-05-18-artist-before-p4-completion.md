# Artist Before P4 Completion Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Artist as the default LamImager creative experience before P4, so P4 can focus on extracting Core SDK and preparing other members.

**Architecture:** Artist becomes a turn-based runtime with a small explicit state machine, validated action schema, Artist-specific events, and Artist artifact metadata. LangGraph remains for Agent Mode only; Artist does not use the graph, and LamTwo remains a long-term ideal that does not affect current six-role runtime behavior.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Pydantic / Vue3 / Pinia / SSE

---

## Scope

This plan upgrades the current Artist prototype into a product-complete Artist Mode before P4.

Current prototype:

```text
artist_service.py + LLM JSON(message + plan) + generate_image + generic agent/image messages
```

Target before P4:

```text
ArtistRuntime + ArtistTurn schema + ArtistSessionState + ArtistArtifact metadata + artist_* SSE events + frontend Artist stream
```

P4 then extracts reusable infrastructure for other members:

```text
PersonaDef / MEMModule / PromptAssembler / LamEvent / Guardrail / billing / protocol
```

---

## Non-Goals

- Do not implement LamTwo runtime.
- Do not let LamTwo persona rules influence Artist behavior.
- Do not remove LangGraph; keep it for Agent Mode.
- Do not implement full Canvas mask UI beyond preserving existing mask/refine hooks.
- Do not build Native Shell or desktop pet UI.
- Do not start Coder, Butler, Sage, Mate, or Creator implementation.

---

## Completion Definition

Artist is complete enough for P4 when all conditions below pass:

- Artist requests run through `ArtistRuntime`, not ad-hoc `artist_orchestrate` logic.
- Artist turn output is validated by Pydantic schema before execution.
- Artist supports `chat_only`, `ask_clarification`, `generate_anchor`, `generate_pack`, `refine_target`, `replace_image`, and `style_reference` actions.
- Anchor-to-pack flow works across turns.
- Generated images are persisted with Artist artifact metadata: `artist_turn_id`, `artifact_type`, `group_id`, `index_in_group`, `parent_url`, `prompt`, `artist_comment`, `status`.
- Artist streaming text is visible in frontend as conversation, not Agent timeline.
- Artist image messages render as Artist artifacts, not generic Agent node output.
- ImageContextResolver result is passed into ArtistRuntime as structured context.
- User feedback like “图3不错 / 图4换掉” updates artifact lineage or feedback metadata.
- Existing Agent Mode still works through LangGraph.
- `py -3.14 -m compileall app` succeeds in backend.
- `npm run build` succeeds in frontend.

---

## Task 1: Add Artist Runtime Schema Tests

**Files:**
- `backend/tests/test_artist_runtime_schemas.py`
- `backend/app/core/artist/__init__.py`
- `backend/app/core/artist/schemas.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_runtime_schemas.py` with tests importing `ArtistAction`, `ArtistActionType`, `ArtistTurn`, `ArtistSessionState`, and `ArtistArtifact` from `app.core.artist.schemas`.
- [ ] Step 2: Add test `test_artist_action_allows_generate_anchor()` that constructs `ArtistAction(type="generate_anchor", prompt="blue cat", image_count=1, image_size="1024x1024")` and asserts `type == "generate_anchor"`.
- [ ] Step 3: Add test `test_artist_turn_rejects_unknown_action_type()` that expects Pydantic validation to fail for `type="unknown"`.
- [ ] Step 4: Add test `test_artist_artifact_requires_artist_turn_id()` that expects Pydantic validation to fail when `artist_turn_id` is missing.
- [ ] Step 5: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_schemas.py` and confirm it fails because `app.core.artist.schemas` does not exist.
- [ ] Step 6: Create `backend/app/core/artist/__init__.py` exporting `ArtistAction`, `ArtistActionType`, `ArtistTurn`, `ArtistSessionState`, `ArtistArtifact`, and `ArtistRuntimePhase`.
- [ ] Step 7: Create `backend/app/core/artist/schemas.py` with Pydantic models:
  - `ArtistActionType = Literal["chat_only", "ask_clarification", "generate_anchor", "generate_pack", "refine_target", "replace_image", "style_reference"]`
  - `ArtistRuntimePhase = Literal["idle", "anchor_pending", "pack_ready", "refining", "waiting_clarification"]`
  - `ArtistAction` fields: `type`, `prompt`, `image_count`, `image_size`, `negative_prompt`, `target_images`, `reference_images`, `replace_index`, `message`
  - `ArtistTurn` fields: `reply_blocks`, `actions`, `next_phase`, `memory_writes`
  - `ArtistSessionState` fields: `session_id`, `phase`, `anchor_group_id`, `last_group_id`, `last_target_url`, `pending_prompt`
  - `ArtistArtifact` fields: `artist_turn_id`, `artifact_type`, `url`, `group_id`, `index_in_group`, `parent_url`, `prompt`, `artist_comment`, `status`
- [ ] Step 8: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_schemas.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_runtime_schemas.py` passes.
- [ ] `py -3.14 -c "from app.core.artist.schemas import ArtistAction; print(ArtistAction(type='chat_only').type)"` prints `chat_only`.

**Commit:** `test: add artist runtime schema coverage`

---

## Task 2: Add Artist State Store

**Files:**
- `backend/tests/test_artist_state_store.py`
- `backend/app/core/artist/state_store.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_state_store.py` with tests for loading a default state and saving/reloading a state.
- [ ] Step 2: In the test, instantiate `ArtistStateStore(base_dir=tmp_path)`, call `load("session-1")`, and assert `phase == "idle"` and `session_id == "session-1"`.
- [ ] Step 3: In the test, save `ArtistSessionState(session_id="session-1", phase="anchor_pending", pending_prompt="cat")`, reload it, and assert the saved values persist.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_state_store.py` and confirm it fails because `state_store.py` does not exist.
- [ ] Step 5: Create `backend/app/core/artist/state_store.py` with `ArtistStateStore` using JSON files under `data/artist_state/` by default.
- [ ] Step 6: Implement `load(session_id: str) -> ArtistSessionState` returning default idle state when no file exists.
- [ ] Step 7: Implement `save(state: ArtistSessionState) -> None` writing UTF-8 JSON with `model_dump()`.
- [ ] Step 8: Run `py -3.14 -m pytest backend/tests/test_artist_state_store.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_state_store.py` passes.

**Commit:** `feat: add artist session state store`

---

## Task 3: Add Artist Action Normalizer

**Files:**
- `backend/tests/test_artist_action_normalizer.py`
- `backend/app/core/artist/action_normalizer.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_action_normalizer.py` with tests for clamping invalid image counts and converting plan-style generate actions.
- [ ] Step 2: Add test `test_normalize_pack_count_uses_requested_count()` using action `generate_pack` with `image_count=9` and assert normalized count remains 9.
- [ ] Step 3: Add test `test_normalize_anchor_count_forces_one()` using action `generate_anchor` with `image_count=6` and assert normalized count becomes 1.
- [ ] Step 4: Add test `test_convert_legacy_generate_plan_step()` with legacy dict `{"tool":"generate_image","params":{"prompt":"cat","n":4,"size":"1024x1024"}}` and assert output action type is `generate_pack`.
- [ ] Step 5: Run `py -3.14 -m pytest backend/tests/test_artist_action_normalizer.py` and confirm it fails.
- [ ] Step 6: Create `backend/app/core/artist/action_normalizer.py` with `normalize_action(action: ArtistAction, default_size: str, default_count: int) -> ArtistAction`.
- [ ] Step 7: Implement count bounds: anchor = 1, pack = 1..9, refine/replace/style = 1.
- [ ] Step 8: Implement `legacy_plan_step_to_action(step: dict, default_size: str, default_count: int) -> ArtistAction | None` for existing `generate_image` plan compatibility.
- [ ] Step 9: Run `py -3.14 -m pytest backend/tests/test_artist_action_normalizer.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_action_normalizer.py` passes.

**Commit:** `feat: normalize artist actions`

---

## Task 4: Add Artist Event Helpers

**Files:**
- `backend/tests/test_artist_events.py`
- `backend/app/core/artist/events.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_events.py` with tests that build `artist_turn_started`, `artist_reply_delta`, `artist_image_ready`, `artist_turn_done` event payloads.
- [ ] Step 2: Assert each payload contains `type`, `session_id`, and `artist_turn_id`.
- [ ] Step 3: Run `py -3.14 -m pytest backend/tests/test_artist_events.py` and confirm it fails.
- [ ] Step 4: Create `backend/app/core/artist/events.py` with helper functions:
  - `artist_turn_started(session_id, artist_turn_id)`
  - `artist_reply_delta(session_id, artist_turn_id, content)`
  - `artist_action_started(session_id, artist_turn_id, action_type)`
  - `artist_image_ready(session_id, artist_turn_id, artifact)`
  - `artist_turn_done(session_id, artist_turn_id, phase)`
- [ ] Step 5: Return plain dict payloads compatible with existing `LamEvent(payload=...)`.
- [ ] Step 6: Run `py -3.14 -m pytest backend/tests/test_artist_events.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_events.py` passes.

**Commit:** `feat: add artist event payload helpers`

---

## Task 5: Add Artist Artifact Metadata Builder

**Files:**
- `backend/tests/test_artist_artifacts.py`
- `backend/app/core/artist/artifacts.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_artifacts.py` with test `test_build_image_artifacts_sets_group_and_indices()`.
- [ ] Step 2: In the test, pass two URLs to `build_image_artifacts()` with `artifact_type="pack"`, `artist_turn_id="turn-1"`, `group_id="group-1"`, and assert indices are 1 and 2.
- [ ] Step 3: Add test `test_artifacts_metadata_serializable()` and assert every artifact `model_dump()` includes `artist_turn_id`, `artifact_type`, `group_id`, `index_in_group`, and `prompt`.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_artifacts.py` and confirm it fails.
- [ ] Step 5: Create `backend/app/core/artist/artifacts.py` with `build_image_artifacts(urls, artifact_type, artist_turn_id, group_id, prompt, parent_url="", artist_comment="") -> list[ArtistArtifact]`.
- [ ] Step 6: Map action type to artifact type with `action_type_to_artifact_type()` returning `anchor`, `pack`, `refine`, `replacement`, or `reference`.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_artifacts.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_artifacts.py` passes.

**Commit:** `feat: add artist artifact metadata builder`

---

## Task 6: Add Artist Turn Parser With Legacy Compatibility

**Files:**
- `backend/tests/test_artist_turn_parser.py`
- `backend/app/core/artist/turn_parser.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_turn_parser.py` with tests for new `actions` format and legacy `plan.steps` format.
- [ ] Step 2: Add test parsing `{"message":"来了","actions":[{"type":"generate_anchor","prompt":"cat"}],"next_phase":"anchor_pending"}` and assert one `generate_anchor` action.
- [ ] Step 3: Add test parsing legacy `{"message":"来了","plan":{"steps":[{"tool":"generate_image","params":{"prompt":"cat","n":4}}]}}` and assert one `generate_pack` action.
- [ ] Step 4: Add test parsing raw non-JSON text and assert `reply_blocks == [raw_text]`, `actions == []`, and `next_phase == "idle"`.
- [ ] Step 5: Run `py -3.14 -m pytest backend/tests/test_artist_turn_parser.py` and confirm it fails.
- [ ] Step 6: Create `backend/app/core/artist/turn_parser.py` with `parse_artist_turn(raw_text: str, default_size: str, default_count: int, fallback_phase: str) -> ArtistTurn`.
- [ ] Step 7: Implement JSON extraction using the existing behavior from `artist_service.py`, but return validated `ArtistTurn`.
- [ ] Step 8: Split message into reply blocks using `||` and sentence punctuation, preserving current `_split_blocks` behavior.
- [ ] Step 9: Run `py -3.14 -m pytest backend/tests/test_artist_turn_parser.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_turn_parser.py` passes.

**Commit:** `feat: parse validated artist turns`

---

## Task 7: Create ArtistRuntime Skeleton

**Files:**
- `backend/tests/test_artist_runtime_unit.py`
- `backend/app/core/artist/runtime.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_runtime_unit.py` with a fake runtime dependency object that does not call external providers.
- [ ] Step 2: Add test `test_runtime_chat_only_returns_no_artifacts()` by injecting a fake LLM response `{"message":"画什么？","actions":[],"next_phase":"idle"}` and assert `artifacts == []`.
- [ ] Step 3: Add test `test_runtime_anchor_action_updates_phase()` with fake LLM response containing `generate_anchor` and fake image generator returning one URL; assert state phase becomes `anchor_pending`.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_unit.py` and confirm it fails.
- [ ] Step 5: Create `backend/app/core/artist/runtime.py` with class `ArtistRuntime` and method `handle_turn(...) -> dict`.
- [ ] Step 6: Constructor dependencies: `state_store`, `llm_client_factory`, `image_generator`, `event_publisher`, `mem`, `prompt_assembler`.
- [ ] Step 7: Implement `handle_turn()` loading `ArtistSessionState`, calling injected LLM, parsing `ArtistTurn`, executing normalized actions through injected image generator, saving state, and returning `message`, `blocks`, `artifacts`, `artist_turn_id`, `phase`, token/cost fields.
- [ ] Step 8: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_unit.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_runtime_unit.py` passes.

**Commit:** `feat: add artist runtime skeleton`

---

## Task 8: Move LLM Prompt Construction Into ArtistRuntime

**Files:**
- `backend/tests/test_artist_runtime_prompt.py`
- `backend/app/core/artist/runtime.py`
- `backend/app/services/artist_service.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_runtime_prompt.py` asserting the runtime prompt contains `PersonaDef("artist")`, current user prompt, defaults, and the action schema text.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_prompt.py` and confirm it fails.
- [ ] Step 3: Move `ARTIST_ROUND_SYSTEM` from `backend/app/services/artist_service.py` into `backend/app/core/artist/runtime.py` as `ARTIST_TURN_SYSTEM`.
- [ ] Step 4: Replace legacy JSON `plan` instruction with new `actions` schema while keeping legacy parse compatibility.
- [ ] Step 5: Include action types and required meanings in the system fragment.
- [ ] Step 6: Keep the existing Artist tone constraints from `PersonaDef("artist")`; do not duplicate identity more than once.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_prompt.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_runtime_prompt.py` passes.
- [ ] `py -3.14 -m compileall backend/app/core/artist/runtime.py backend/app/services/artist_service.py` succeeds.

**Commit:** `refactor: move artist turn prompt into runtime`

---

## Task 9: Integrate ImageContextResolver Result Into ArtistRuntime

**Files:**
- `backend/tests/test_artist_runtime_image_context.py`
- `backend/app/core/artist/schemas.py`
- `backend/app/core/artist/runtime.py`
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_runtime_image_context.py` with test passing `image_context={"mode":"edit_target","target_images":["https://x/a.png"]}` to runtime and asserting LLM prompt includes `edit_target` and target image URL.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_image_context.py` and confirm it fails.
- [ ] Step 3: Add `image_context: dict = {}` to runtime `handle_turn()` input.
- [ ] Step 4: Add `image_context` to `ArtistTurn` construction context, not to persisted state.
- [ ] Step 5: In `generate_service.py`, preserve the existing `ImageContextResolver` result as a dict and pass it into `_run_artist_orchestrate()` and then ArtistRuntime.
- [ ] Step 6: Ensure `ask_clarification` mode short-circuits into an Artist text message instead of generic agent failure.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_image_context.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_runtime_image_context.py` passes.
- [ ] Manual log check shows Artist receives resolver mode for “图3线稿化”.

**Commit:** `feat: pass image context into artist runtime`

---

## Task 10: Replace artist_orchestrate Internals With ArtistRuntime

**Files:**
- `backend/tests/test_artist_orchestrate.py`
- `backend/app/services/artist_service.py`
- `backend/app/core/artist/runtime.py`

**Steps:**
- [ ] Step 1: Extend `backend/tests/test_artist_orchestrate.py` with assertion that result contains `artist_turn_id` and each artifact metadata includes `artifact_type`.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_orchestrate.py` and confirm the new assertions fail.
- [ ] Step 3: Update `artist_orchestrate()` to instantiate `ArtistRuntime` with production dependencies: `LLMClient`, `generate_images_core`, `MEMModule`, `PromptAssembler`, `ArtistStateStore`, and LamEvent publisher.
- [ ] Step 4: Keep function signature stable for `generate_service.py` compatibility.
- [ ] Step 5: Return runtime fields: `message`, `blocks`, `artifacts`, `artist_turn_id`, `phase`, `tokens_in`, `tokens_out`, `cost`.
- [ ] Step 6: Remove duplicated execution loop from `artist_service.py` after runtime integration.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_orchestrate.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_orchestrate.py` passes.
- [ ] `py -3.14 -m compileall backend/app/services/artist_service.py backend/app/core/artist` succeeds.

**Commit:** `refactor: route artist orchestrate through ArtistRuntime`

---

## Task 11: Persist Artist Artifact Metadata In Messages

**Files:**
- `backend/tests/test_artist_message_persistence.py`
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_message_persistence.py` with a unit test for a helper `build_artist_image_message_metadata(artist_result)`.
- [ ] Step 2: Assert metadata includes `persona="artist"`, `artist_turn_id`, `artist_artifacts`, `images`, and `final_images`.
- [ ] Step 3: Run `py -3.14 -m pytest backend/tests/test_artist_message_persistence.py` and confirm it fails.
- [ ] Step 4: In `backend/app/services/generate_service.py`, add helper `build_artist_image_message_metadata(artist_result: dict) -> dict`.
- [ ] Step 5: Use this helper in `_run_artist_orchestrate()` when adding the image message.
- [ ] Step 6: Change message content from generic `已生成 N 张图片` to use Artist text if available: `artist_result.get("image_caption") or f"出了 {len(all_urls)} 张。"`.
- [ ] Step 7: Preserve `metadata.images` and `metadata.final_images` for backward compatibility.
- [ ] Step 8: Run `py -3.14 -m pytest backend/tests/test_artist_message_persistence.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_message_persistence.py` passes.

**Commit:** `feat: persist artist artifact metadata in messages`

---

## Task 12: Add Artist State Transitions For Anchor Flow

**Files:**
- `backend/tests/test_artist_anchor_flow.py`
- `backend/app/core/artist/runtime.py`
- `backend/app/core/artist/state_store.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_anchor_flow.py` with a two-turn runtime test.
- [ ] Step 2: First turn uses fake LLM action `generate_anchor`; assert saved phase is `anchor_pending` and `anchor_group_id` is non-empty.
- [ ] Step 3: Second turn prompt is `对，就这个方向`; fake LLM action is `generate_pack`; assert saved phase is `pack_ready` and `last_group_id` is non-empty.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_anchor_flow.py` and confirm it fails.
- [ ] Step 5: In runtime, when action type is `generate_anchor`, create a new `group_id`, save `anchor_group_id`, set phase to `anchor_pending`, and set `pending_prompt` to the action prompt.
- [ ] Step 6: When action type is `generate_pack`, use `anchor_group_id` or create new `group_id`, set `last_group_id`, and set phase to `pack_ready`.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_anchor_flow.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_anchor_flow.py` passes.

**Commit:** `feat: add artist anchor-to-pack state transitions`

---

## Task 13: Add Replace Image And Refine State Transitions

**Files:**
- `backend/tests/test_artist_refine_replace_flow.py`
- `backend/app/core/artist/runtime.py`
- `backend/app/core/artist/artifacts.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_refine_replace_flow.py` with tests for `replace_image` and `refine_target` actions.
- [ ] Step 2: Add test that `replace_image` with `replace_index=4` creates artifact type `replacement`, preserves `index_in_group=4`, and phase remains `pack_ready`.
- [ ] Step 3: Add test that `refine_target` with `target_images=["https://x/a.png"]` creates artifact type `refine`, sets `parent_url`, and phase becomes `refining`.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_refine_replace_flow.py` and confirm it fails.
- [ ] Step 5: Implement `replace_image` execution in runtime using `replace_index` and current `last_group_id`.
- [ ] Step 6: Implement `refine_target` execution using target image as `parent_url` and action reference images.
- [ ] Step 7: Run `py -3.14 -m pytest backend/tests/test_artist_refine_replace_flow.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_refine_replace_flow.py` passes.

**Commit:** `feat: support artist refine and replacement actions`

---

## Task 14: Add Artist Feedback Extraction

**Files:**
- `backend/tests/test_artist_feedback.py`
- `backend/app/core/artist/feedback.py`
- `backend/app/services/artist_service.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_feedback.py` with tests for parsing `图3不错`, `图4换掉`, and `这张不行`.
- [ ] Step 2: Assert `extract_artist_feedback("图3不错")` returns `[{"index":3,"sentiment":"positive"}]`.
- [ ] Step 3: Assert `extract_artist_feedback("图4换掉")` returns `[{"index":4,"sentiment":"negative","intent":"replace"}]`.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_artist_feedback.py` and confirm it fails.
- [ ] Step 5: Create `backend/app/core/artist/feedback.py` with regex-based `extract_artist_feedback(text: str) -> list[dict]`.
- [ ] Step 6: In `artist_service.py` or runtime, call extractor before LLM decision and pass feedback into memory write context.
- [ ] Step 7: Write feedback into MEM `output_index` or `conversation_summaries` with tags `artist`, `feedback`, and sentiment.
- [ ] Step 8: Run `py -3.14 -m pytest backend/tests/test_artist_feedback.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_feedback.py` passes.

**Commit:** `feat: extract artist image feedback`

---

## Task 15: Add Frontend Artist Stream State

**Files:**
- `frontend/src/stores/session.ts`
- `frontend/src/types/index.ts`
- `frontend/src/stores/session.artist.spec.ts`

**Steps:**
- [ ] Step 1: Create `frontend/src/stores/session.artist.spec.ts` with tests for `handleArtistToken` and `flushArtistBuffer` if the frontend test runner exists; if no test runner exists, create a TypeScript compile-only test module under `frontend/src/stores/__artist_stream_compile_check.ts` and import store types.
- [ ] Step 2: Add `ArtistStreamState` interface to `frontend/src/types/index.ts` with fields `sessionId`, `artistTurnId`, `status`, `content`, `artifacts`, `startedAt`.
- [ ] Step 3: Add `artistStreamStates = reactive(new Map<string, ArtistStreamState>())` to `frontend/src/stores/session.ts`.
- [ ] Step 4: Implement `getArtistStream(sessionId)`, `clearArtistStream(sessionId)`, `handleArtistTurnStarted`, `handleArtistToken`, `handleArtistImageReady`, and `flushArtistBuffer`.
- [ ] Step 5: `handleArtistToken` appends delta text to current Artist stream content.
- [ ] Step 6: `flushArtistBuffer` marks the Artist stream `done` and keeps content visible until messages refetch.
- [ ] Step 7: Run `npm run build` and fix TypeScript errors.

**Verification:**
- [ ] `npm run build` succeeds in `frontend`.
- [ ] `handleArtistToken` is no longer an empty function.

**Commit:** `feat: add frontend artist stream state`

---

## Task 16: Route artist_* SSE Events In Sessions.vue

**Files:**
- `frontend/src/views/Sessions.vue`
- `frontend/src/stores/session.ts`

**Steps:**
- [ ] Step 1: In the SSE event switch in `Sessions.vue`, add cases for `artist_turn_started`, `artist_reply_delta`, `artist_action_started`, `artist_image_ready`, and `artist_turn_done`.
- [ ] Step 2: Route `artist_turn_started` to `store.handleArtistTurnStarted(eventSid, event)`.
- [ ] Step 3: Route `artist_reply_delta` and existing `artist_token` to `store.handleArtistToken(eventSid, event)` for compatibility.
- [ ] Step 4: Route `artist_image_ready` to `store.handleArtistImageReady(eventSid, event)`.
- [ ] Step 5: Route `artist_turn_done` and existing `artist_done` to `store.flushArtistBuffer(eventSid)`.
- [ ] Step 6: Run `npm run build` and fix TypeScript errors.

**Verification:**
- [ ] `npm run build` succeeds in `frontend`.
- [ ] Searching `artist_reply_delta` in `frontend/src` shows it is handled in `Sessions.vue`.

**Commit:** `feat: route artist SSE events in frontend`

---

## Task 17: Render Artist Stream In MessageList

**Files:**
- `frontend/src/components/session/MessageList.vue`
- `frontend/src/views/Sessions.vue`
- `frontend/src/types/index.ts`

**Steps:**
- [ ] Step 1: Add prop `artistStreamState: ArtistStreamState | null` to `MessageList.vue`.
- [ ] Step 2: Pass `:artist-stream-state="artistStreamState"` from `Sessions.vue` using a computed `store.getArtistStream(currentSessionId.value || '') || null`.
- [ ] Step 3: In `MessageList.vue`, render an assistant message when `artistStreamState` exists and status is not `done`.
- [ ] Step 4: Display `artistStreamState.content` as normal text, not as Agent timeline.
- [ ] Step 5: Render any `artistStreamState.artifacts` as inline thumbnails with `open-image` event.
- [ ] Step 6: Run `npm run build` and fix TypeScript errors.

**Verification:**
- [ ] `npm run build` succeeds in `frontend`.
- [ ] Artist streaming UI does not render inside `.agent-inline-steps`.

**Commit:** `feat: render artist stream as conversation`

---

## Task 18: Add Artist Image Message Rendering Path

**Files:**
- `frontend/src/components/session/MessageList.vue`
- `frontend/src/components/session/ArtistImageMessageCard.vue`

**Steps:**
- [ ] Step 1: Create `frontend/src/components/session/ArtistImageMessageCard.vue` accepting `msg: Message` and rendering `msg.metadata.artist_artifacts` when available.
- [ ] Step 2: In the card, display grouped thumbnails with labels derived from `artifact_type` and `index_in_group`.
- [ ] Step 3: Emit `open-image`, `download-all`, `download-selected`, `compare-selected`, and `enter-refine` events matching `ImageMessageCard.vue`.
- [ ] Step 4: In `MessageList.vue`, before generic `agent` handling, detect `msg.metadata?.persona === 'artist' && msg.metadata?.artist_artifacts` and render `ArtistImageMessageCard`.
- [ ] Step 5: Preserve fallback to existing Agent rendering when `artist_artifacts` is absent.
- [ ] Step 6: Run `npm run build` and fix TypeScript errors.

**Verification:**
- [ ] `npm run build` succeeds in `frontend`.
- [ ] Searching `ArtistImageMessageCard` in `frontend/src` shows it is imported and rendered by `MessageList.vue`.

**Commit:** `feat: render artist artifacts separately from agent timeline`

---

## Task 19: Add Artist Settings Panel

**Files:**
- `frontend/src/components/session/ComposerControls.vue`
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: Add a collapsible Artist settings row in `ComposerControls.vue` that only appears when `artistMode` is true.
- [ ] Step 2: Add controls for `artistModelMode` values `auto` and `fixed`.
- [ ] Step 3: Add pack count buttons `4`, `6`, `9` for Artist mode while preserving existing normal mode counts.
- [ ] Step 4: Emit `update:artistModelMode` and `update:artistPackCount`.
- [ ] Step 5: In `Sessions.vue`, add refs `artistModelMode = ref('auto')` and `artistPackCount = ref(6)`.
- [ ] Step 6: When `artistMode` is true and no custom count is set, send `image_count = artistPackCount.value`.
- [ ] Step 7: Run `npm run build` and fix TypeScript errors.

**Verification:**
- [ ] `npm run build` succeeds in `frontend`.
- [ ] Artist mode shows pack count options `4`, `6`, `9`.

**Commit:** `feat: add artist settings panel`

---

## Task 20: Add Backend Request Fields For Artist Options

**Files:**
- `backend/tests/test_artist_generate_request.py`
- `backend/app/schemas/session.py`
- `frontend/src/stores/session.ts`
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_generate_request.py` asserting `GenerateRequest(prompt='x', artist_model_mode='auto', artist_pack_count=6)` parses.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_generate_request.py` and confirm it fails.
- [ ] Step 3: Add fields to `GenerateRequest`: `artist_model_mode: str = "auto"`, `artist_pack_count: int = Field(6, ge=1, le=9)`, and `artist_anchor_first: bool = True`.
- [ ] Step 4: Update frontend store `generate()` TypeScript data type to include `artist_model_mode`, `artist_pack_count`, and `artist_anchor_first`.
- [ ] Step 5: In `Sessions.vue`, send these fields when `artistMode.value` is true.
- [ ] Step 6: Run backend test and frontend build.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_generate_request.py` passes.
- [ ] `npm run build` succeeds in `frontend`.

**Commit:** `feat: add artist request options`

---

## Task 21: Use Artist Options In Runtime

**Files:**
- `backend/tests/test_artist_runtime_options.py`
- `backend/app/services/generate_service.py`
- `backend/app/services/artist_service.py`
- `backend/app/core/artist/runtime.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_runtime_options.py` asserting `artist_pack_count=9` is used as default count for `generate_pack` when action count is missing.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_runtime_options.py` and confirm it fails.
- [ ] Step 3: Pass `artist_model_mode`, `artist_pack_count`, and `artist_anchor_first` from `_run_artist_orchestrate()` into `artist_orchestrate()` and ArtistRuntime.
- [ ] Step 4: In runtime prompt context, include `Artist model mode`, `Artist pack count`, and `Anchor first` lines.
- [ ] Step 5: Use `artist_pack_count` as default count for pack actions.
- [ ] Step 6: Run test and compile backend.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_runtime_options.py` passes.
- [ ] `py -3.14 -m compileall backend/app/services/generate_service.py backend/app/services/artist_service.py backend/app/core/artist` succeeds.

**Commit:** `feat: apply artist options in runtime`

---

## Task 22: Make Artist Clarification A First-Class Message

**Files:**
- `backend/tests/test_artist_clarification.py`
- `backend/app/services/generate_service.py`
- `backend/app/core/artist/runtime.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_clarification.py` verifying resolver `ask_clarification` produces text message metadata `{"persona":"artist","dialog":true,"clarification":true}`.
- [ ] Step 2: Run `py -3.14 -m pytest backend/tests/test_artist_clarification.py` and confirm it fails.
- [ ] Step 3: In `generate_service.py`, when ImageContextResolver returns `ask_clarification`, call Artist message persistence path instead of generic agent error/done path.
- [ ] Step 4: Save a text message with clarification content and metadata `persona=artist`, `dialog=true`, `clarification=true`.
- [ ] Step 5: Publish `artist_turn_done` with phase `waiting_clarification`.
- [ ] Step 6: Run the test and compile backend.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_clarification.py` passes.

**Commit:** `feat: make artist clarification first-class`

---

## Task 23: Preserve Agent Mode LangGraph Behavior

**Files:**
- `backend/tests/test_agent_mode_still_uses_graph.py`
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_agent_mode_still_uses_graph.py` with a test patching `_run_agent_mode_graph` and `_run_artist_orchestrate`.
- [ ] Step 2: Assert `agent_persona='agent'` calls `_run_agent_mode_graph` and does not call `_run_artist_orchestrate`.
- [ ] Step 3: Assert `agent_persona='artist'` calls `_run_artist_orchestrate` and does not call `_run_agent_mode_graph`.
- [ ] Step 4: Run `py -3.14 -m pytest backend/tests/test_agent_mode_still_uses_graph.py` and confirm it fails if routing is broken.
- [ ] Step 5: Adjust routing in `generate_service.py` only if needed; keep current `if persona_name == "artist"` split.
- [ ] Step 6: Run the test and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_agent_mode_still_uses_graph.py` passes.

**Commit:** `test: preserve agent graph and artist runtime split`

---

## Task 24: End-To-End Backend Smoke Test For Artist

**Files:**
- `backend/tests/test_artist_e2e_smoke.py`

**Steps:**
- [ ] Step 1: Create `backend/tests/test_artist_e2e_smoke.py` with mocked LLM and image provider.
- [ ] Step 2: Test prompt `帮我做一套猫咪表情包，6张` with first fake LLM response generating anchor; assert one image and message metadata artifact type `anchor`.
- [ ] Step 3: Test next prompt `对，就这个方向` with fake LLM response generating pack; assert six images and artifact type `pack`.
- [ ] Step 4: Test prompt `图4换一张` with fake LLM response `replace_image`; assert one replacement artifact with `index_in_group=4`.
- [ ] Step 5: Run `py -3.14 -m pytest backend/tests/test_artist_e2e_smoke.py` and confirm it passes.

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_artist_e2e_smoke.py` passes.

**Commit:** `test: add artist end-to-end smoke coverage`

---

## Task 25: Frontend Build And Manual Artist Checklist

**Files:**
- `docs/plans/2026-05-18-artist-before-p4-completion.md`

**Steps:**
- [ ] Step 1: Run `npm run build` in `frontend`.
- [ ] Step 2: Run `py -3.14 -m compileall app` in `backend`.
- [ ] Step 3: Start backend with `py -3.14 -m uvicorn app.main:app --reload --port 8000` from `backend`.
- [ ] Step 4: Start frontend with `npm run dev` from `frontend`.
- [ ] Step 5: Create a new session and send `帮我做一套猫咪表情包，6张，Q版冷蓝调` in Artist mode.
- [ ] Step 6: Confirm the first turn produces one anchor image and Artist text appears as conversational stream.
- [ ] Step 7: Send `对，就这个方向` and confirm a pack of six images appears as Artist artifacts.
- [ ] Step 8: Send `图4换一张` and confirm only the fourth image is replaced.
- [ ] Step 9: Send `图3线稿化` and confirm the selected target image is passed into edit/refine flow.
- [ ] Step 10: Send a normal Agent mode request and confirm LangGraph timeline still appears.

**Verification:**
- [ ] `frontend` build succeeds.
- [ ] `backend` compile succeeds.
- [ ] Manual Artist checklist steps 5-10 pass.

**Commit:** `test: verify artist mode before P4`

---

## Task 26: Update Documentation After Implementation

**Files:**
- `docs/plans/PLAN.md`
- `docs/ROADMAP.md`
- `docs/plans/2026-05-14-artist-mode-design.md`
- `AGENTS.md`

**Steps:**
- [ ] Step 1: In `docs/plans/PLAN.md`, mark Artist completion as the final gate before P4.
- [ ] Step 2: In `docs/ROADMAP.md`, update P3B-10 details to reference ArtistRuntime, ArtistTurn schema, Artist events, and artifact metadata.
- [ ] Step 3: In `docs/plans/2026-05-14-artist-mode-design.md`, add a short “Implementation status” section listing completed runtime pieces.
- [ ] Step 4: In `AGENTS.md`, add ArtistRuntime and Artist artifact files to Code Index if they exist.
- [ ] Step 5: Run a grep for `Artist Default Experience` and ensure no doc claims the prototype JSON-plan implementation is the final architecture.

**Verification:**
- [ ] `rg "ArtistRuntime|ArtistTurn|artist_artifacts" docs AGENTS.md` shows current docs reference the implemented architecture.

**Commit:** `docs: sync artist completion before P4`
