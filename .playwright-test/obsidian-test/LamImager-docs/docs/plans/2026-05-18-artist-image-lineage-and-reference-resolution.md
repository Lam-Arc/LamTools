# Artist Image Lineage And Reference Resolution Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Artist resolve “原图” as the root source image of the current image lineage, and record enough lineage in CON to explain which image each generation referenced.

**Architecture:** Every session image becomes a lightweight artifact node with `artifact_id`, `parent_artifact_id`, `root_artifact_id`, and URL lineage. The resolver uses explicit selection first, then explicit text refs, then root/parent/latest semantics; if root cannot be determined, it returns clarification instead of guessing. Artist output metadata and CON output_index both persist lineage fields, with data URLs truncated in CON.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Pydantic / Vue3 / Pinia / JSON metadata / MEM CON

---

## Task 1: Add Resolver Tests For Original Image Semantics

**Files:**
- `backend/tests/test_image_context_resolver.py`
- `backend/app/services/image_context_resolver.py`

**Steps:**
- [x] Step 1: Create `test_original_ref_uses_root_artifact_url()` with a generated latest image whose root URL is an earlier upload; prompt is `参考原图，线条不要太乱`; assert resolution mode is `edit_target`, `target_images == [root_url]`, and reason contains `original`.
- [x] Step 2: Create `test_original_ref_asks_when_root_missing()` with a latest generated image but no `root_url`; prompt is `参考原图改一下`; assert mode is `ask_clarification`.
- [x] Step 3: Run `py -3.14 -m pytest tests/test_image_context_resolver.py -v` and confirm it fails before implementation.

**Verification:**
- [x] `py -3.14 -m pytest tests/test_image_context_resolver.py -v` passes.

**Commit:** `test: cover artist original image resolution`

---

## Task 2: Extend SessionImage And Resolver Lineage Rules

**Files:**
- `backend/app/services/image_context_resolver.py`

**Steps:**
- [x] Step 1: Add `artifact_id`, `parent_artifact_id`, `root_artifact_id`, `parent_url`, `root_url`, `artifact_type`, and `is_user_upload` fields to `SessionImage`.
- [x] Step 2: Add regex helper `is_original_ref(prompt)` matching `原图`, `原始图`, `最开始那张`, `初始参考`.
- [x] Step 3: In `resolve_image_context()`, before generic intent-based selection, if prompt contains original-ref text, resolve to the latest focus image's `root_url`; if absent, resolve to the earliest user-upload/root image; if still absent, return `ask_clarification`.
- [x] Step 4: Add reason strings that include `original root` or `original ambiguous`.

**Verification:**
- [x] `py -3.14 -m pytest tests/test_image_context_resolver.py -v` passes.

**Commit:** `feat: resolve original image references by lineage root`

---

## Task 3: Persist Artist Artifact Lineage Metadata

**Files:**
- `backend/tests/test_artist_artifacts.py`
- `backend/app/core/artist/schemas.py`
- `backend/app/core/artist/artifacts.py`
- `backend/app/services/generate_service.py`
- `backend/app/services/artist_service.py`

**Steps:**
- [x] Step 1: Extend `ArtistArtifact` with `artifact_id`, `parent_artifact_id`, `root_artifact_id`, `root_url`, and `source_message_id` defaulting to empty strings.
- [x] Step 2: Update `build_image_artifacts()` to accept optional lineage fields and set a stable generated `artifact_id` for each image.
- [x] Step 3: Update `build_artist_image_message_metadata()` and Artist artifact dict conversion to include all lineage fields.
- [x] Step 4: When runtime builds refine/replace artifacts, pass `parent_url` from action target when available and inherit root fields from image context if provided.

**Verification:**
- [x] `py -3.14 -m pytest tests/test_artist_artifacts.py tests/test_artist_message_persistence.py -v` passes.

**Commit:** `feat: persist artist artifact lineage metadata`

---

## Task 4: Build Session Images From Artist Metadata

**Files:**
- `backend/tests/test_image_context_resolver.py`
- `backend/app/services/generate_service.py`

**Steps:**
- [x] Step 1: Update `_build_session_images()` so agent messages with `metadata.artist_artifacts` produce `SessionImage` objects with artifact lineage fields.
- [x] Step 2: For generic image messages without artifact metadata, create root `SessionImage` objects using URL as `root_url` and `is_user_upload=True` when message role is `user`.
- [x] Step 3: Preserve current `metadata.images` fallback for backward compatibility.
- [x] Step 4: Add a test that latest generated artifact with `root_url` resolves `参考原图` to that root URL.

**Verification:**
- [x] `py -3.14 -m pytest tests/test_image_context_resolver.py -v` passes.

**Commit:** `feat: build image context from artist lineage metadata`

---

## Task 5: Write CON Output Index With Lineage

**Files:**
- `backend/tests/test_artist_con_lineage.py`
- `backend/app/core/mem/writer.py`
- `backend/app/services/artist_service.py`

**Steps:**
- [x] Step 1: Extend `write_output_index()` to accept `artifact_id`, `parent_artifact_id`, `root_artifact_id`, `parent_url`, `root_url`, and `lineage_note`.
- [x] Step 2: In `artist_service.py`, when writing `output_index`, include lineage fields from artifact metadata and truncate data URLs to 200 characters plus `...`.
- [x] Step 3: Add a unit test that writing output_index preserves lineage fields and truncates data URL root fields.

**Verification:**
- [x] `py -3.14 -m pytest tests/test_artist_con_lineage.py -v` passes.

**Commit:** `feat: record artist lineage in CON output index`

---

## Task 6: Final Verification

**Files:**
- `backend/tests/test_image_context_resolver.py`
- `backend/tests/test_artist_con_lineage.py`
- `backend/tests/test_artist_artifacts.py`
- `frontend/src/components/session/MessageList.vue`

**Steps:**
- [x] Step 1: Run all backend tests.
- [x] Step 2: Run frontend build.
- [ ] Step 3: Manually test a session: upload image → generate derived image → send `参考原图，线条不要太乱`; verify logs show original/root resolution.

**Verification:**
- [x] `py -3.14 -m pytest tests/ --tb=short -q` passes.
- [x] `npm run build` succeeds in frontend.

**Commit:** `test: verify artist image lineage resolution`
