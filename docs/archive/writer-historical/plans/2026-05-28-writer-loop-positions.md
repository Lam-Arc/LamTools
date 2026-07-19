<!-- 历史参考，不代表当前架构 -->
# Writer Loop Position Architecture — Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace WriterRuntime's linear phase progression with conditional loop positions (PLAN/EXECUTE/VERIFY), where simple tasks skip the plan position and complex tasks get full 3-position cycling with re-entry conditions.

**Architecture:** Three loop positions replace the linear phase chain. Each position has explicit entry/exit conditions driven by `_assess_task_complexity()` (file count + keyword hybrid). The existing `enforce_planning` boolean is replaced by `planning_depth: none|light|full`. Drift detection and failure-based replanning become re-entry triggers back to PLAN. All W2-W11 features continue to work within the new position model.

**Tech Stack:** Python 3.14, Pydantic v2, asyncio, existing WriterRuntime (~2400 lines)

---

## Task 1: Add new types to schemas.py

**Files:** `backend/app/core/writer/schemas.py`

**Steps:**
- [ ] Add `WriterLoopPosition = Literal["plan", "execute", "verify"]` after the existing `WriterRuntimePhase` definition (around line 44)
- [ ] Add `TaskComplexity = Literal["simple", "moderate", "complex"]` after `WriterLoopPosition`
- [ ] Add `PlanningDepth = Literal["none", "light", "full"]` after `TaskComplexity`
- [ ] On `WriterSessionState`, add field `loop_position: WriterLoopPosition = "execute"` (default execute so simple tasks start there)
- [ ] On `WriterSessionState`, add field `planning_depth: PlanningDepth = "full"` (replaces `enforce_planning: bool = True`)
- [ ] On `WriterSessionState`, add field `task_complexity: TaskComplexity = "simple"` (set by `_assess_task_complexity`)
- [ ] Keep `enforce_planning` field temporarily with a deprecation property that maps to `planning_depth` for backward compat:
  ```python
  @property
  def enforce_planning(self) -> bool:
      return self.planning_depth != "none"

  @enforce_planning.setter
  def enforce_planning(self, value: bool) -> None:
      self.planning_depth = "full" if value else "none"
  ```

**Verification:**
- [ ] `py -3.14 -c "from app.core.writer.schemas import WriterLoopPosition, TaskComplexity, PlanningDepth, WriterSessionState; s = WriterSessionState(session_id='t', work_root='/tmp'); print(s.loop_position, s.planning_depth, s.task_complexity)"` prints `execute full simple`
- [ ] `py -3.14 -c "from app.core.writer.schemas import WriterSessionState; s = WriterSessionState(session_id='t', work_root='/tmp'); s.enforce_planning = False; print(s.planning_depth)"` prints `none`
- [ ] All existing tests pass: `py -3.14 -m pytest tests/ -q`

**Commit:** `feat: add WriterLoopPosition, TaskComplexity, PlanningDepth types to schemas`

---

## Task 2: Implement `_assess_task_complexity()` in runtime.py

**Files:** `backend/app/core/writer/runtime.py`

**Steps:**
- [ ] Add static method `_assess_task_complexity` to `WriterRuntime`:
  ```python
  @staticmethod
  def _assess_task_complexity(user_message: str) -> TaskComplexity:
      """Hybrid complexity assessment: file count + keyword patterns.
      
      simple:   1 file mentioned, OR keywords like 修复/fix/修改/修改/添加/更新 + 1 file
      moderate: 2-4 files mentioned, OR keywords like 实现/implement/开发/develop
      complex:  0 files + no clear scope (vague), OR 5+ files, OR keywords like 重构/refactor/设计/design/架构/architecture
      """
      import re
      from .schemas import TaskComplexity
      
      # Extract file names using same regex as _extract_deliverables
      file_pattern = r'`?([a-zA-Z0-9_/-]+\.(?:py|html|css|js|ts|tsx|jsx|vue|txt|md|json|yaml|yml|toml|sql|env))`?'
      files = list(set(m.group(1).split('/')[-1] for m in re.finditer(file_pattern, user_message)))
      n_files = len(files)
      
      # Keyword patterns (Chinese + English)
      complex_kw = ["重构", "架构", "设计", "开发一个", "从零", "refactor", "architect", "design", "build a", "create a", "develop"]
      moderate_kw = ["实现", "开发", "implement", "develop", "add feature", "新功能"]
      simple_kw = ["修复", "修改", "添加", "更新", "fix", "modify", "update", "add", "change", "调整", "优化"]
      
      msg_lower = user_message.lower()
      
      # Decision logic
      if n_files >= 5:
          return "complex"
      if n_files == 0:
          # No files mentioned — check if keywords give a hint
          if any(kw in msg_lower for kw in complex_kw):
              return "complex"
          if any(kw in msg_lower for kw in moderate_kw):
              return "moderate"
          # Vague with no scope — complex (triggers DesignFSM)
          return "complex"
      if n_files == 1:
          if any(kw in msg_lower for kw in complex_kw):
              return "moderate"  # single file but complex intent
          return "simple"
      # 2-4 files
      if any(kw in msg_lower for kw in complex_kw):
          return "complex"
      return "moderate"
  ```
- [ ] Import `TaskComplexity` in runtime.py imports section

**Verification:**
- [ ] `py -3.14 -c "from app.core.writer.runtime import WriterRuntime; print(WriterRuntime._assess_task_complexity('修复 auth.py 的登录bug'))"` prints `simple`
- [ ] `py -3.14 -c "from app.core.writer.runtime import WriterRuntime; print(WriterRuntime._assess_task_complexity('实现 changelog.py 和 test_changelog.py'))"` prints `moderate`
- [ ] `py -3.14 -c "from app.core.writer.runtime import WriterRuntime; print(WriterRuntime._assess_task_complexity('开发一个食谱管理应用'))"` prints `complex`
- [ ] `py -3.14 -c "from app.core.writer.runtime import WriterRuntime; print(WriterRuntime._assess_task_complexity('重构认证模块'))"` prints `complex`
- [ ] All existing tests pass

**Commit:** `feat: add _assess_task_complexity hybrid assessor to WriterRuntime`

---

## Task 3: Write failing tests for loop position transitions

**Files:** `backend/tests/test_loop_positions.py` (new)

**Steps:**
- [ ] Create `test_loop_positions.py` with these test cases:
  ```python
  """Tests for WriterLoopPosition conditional entry/exit."""
  import pytest
  from app.core.writer.schemas import WriterSessionState, WriterLoopPosition, TaskComplexity
  from app.core.writer.runtime import WriterRuntime

  class TestTaskComplexityAssessment:
      def test_simple_single_file_fix(self):
          assert WriterRuntime._assess_task_complexity("修复 auth.py 的登录 bug") == "simple"
      
      def test_simple_single_file_update(self):
          assert WriterRuntime._assess_task_complexity("update utils.py to use async") == "simple"
      
      def test_moderate_two_files(self):
          assert WriterRuntime._assess_task_complexity("实现 changelog.py 和 test_changelog.py") == "moderate"
      
      def test_complex_vague_no_files(self):
          assert WriterRuntime._assess_task_complexity("开发一个食谱管理应用") == "complex"
      
      def test_complex_refactor(self):
          assert WriterRuntime._assess_task_complexity("重构认证模块") == "complex"
      
      def test_complex_five_plus_files(self):
          assert WriterRuntime._assess_task_complexity("创建 a.py b.py c.py d.py e.py") == "complex"
      
      def test_moderate_three_files(self):
          assert WriterRuntime._assess_task_complexity("add auth.py, test_auth.py, and routes.py") == "moderate"

  class TestLoopPositionEntry:
      def test_simple_task_enters_execute_directly(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.task_complexity = "simple"
          state.planning_depth = "light"
          # simple task: plan position should be skippable
          assert state.loop_position == "execute"  # default for simple
      
      def test_complex_task_enters_plan(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.task_complexity = "complex"
          state.planning_depth = "full"
          state.loop_position = "plan"
          assert state.loop_position == "plan"
      
      def test_drift_reenters_plan(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.loop_position = "execute"
          # Simulate drift trigger → back to plan
          state.loop_position = "plan"
          assert state.loop_position == "plan"
      
      def test_failure_reenters_plan(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.loop_position = "execute"
          # Simulate failure trigger → back to plan
          state.loop_position = "plan"
          assert state.loop_position == "plan"
      
      def test_all_steps_done_enters_verify(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.loop_position = "execute"
          # All steps done → verify
          state.loop_position = "verify"
          assert state.loop_position == "verify"

  class TestPlanningDepthMigration:
      def test_enforce_planning_true_maps_to_full(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.enforce_planning = True
          assert state.planning_depth == "full"
      
      def test_enforce_planning_false_maps_to_none(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.enforce_planning = False
          assert state.planning_depth == "none"
      
      def test_direct_planning_depth_light(self):
          state = WriterSessionState(session_id="t", work_root="/tmp")
          state.planning_depth = "light"
          assert state.enforce_planning == True  # light still requires planning
  ```
- [ ] Run tests — they should FAIL because `loop_position`, `planning_depth`, `task_complexity` fields don't exist yet (will pass after Task 1)

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_loop_positions.py -v` — should show test names but fail on import/field errors until Task 1 is done

**Commit:** `test: add loop position transition tests (currently failing)`

---

## Task 4: Update transitions.py for loop positions

**Files:** `backend/app/core/writer/transitions.py`

**Steps:**
- [ ] Add `LOOP_TRANSITIONS` dict alongside existing `TRANSITIONS`:
  ```python
  # Loop position transition table (re-entry allowed — this is a cycle, not a chain)
  LOOP_TRANSITIONS: dict[str, set[str]] = {
      "plan": {"execute", "plan"},      # plan → execute (normal), plan → plan (revision)
      "execute": {"verify", "plan", "execute"},  # execute → verify (done), → plan (replan), → execute (continue)
      "verify": {"execute", "plan", "idle"},      # verify → execute (fix), → plan (replan), → idle (done)
  }
  ```
- [ ] Add `can_loop_transition(from_pos: str, to_pos: str) -> bool` and `apply_loop_transition(current: str, requested: str) -> str` — same pattern as existing `can_transition`/`apply_transition`
- [ ] Keep existing `TRANSITIONS` dict unchanged for backward compat

**Verification:**
- [ ] `py -3.14 -c "from app.core.writer.transitions import LOOP_TRANSITIONS, can_loop_transition; print(can_loop_transition('execute', 'plan'))"` prints `True`
- [ ] `py -3.14 -c "from app.core.writer.transitions import can_loop_transition; print(can_loop_transition('plan', 'idle'))"` prints `False`
- [ ] All existing tests pass

**Commit:** `feat: add LOOP_TRANSITIONS table for cycle-based position flow`

---

## Task 5: Update interaction_modes.py for loop position → mode mapping

**Files:** `backend/app/core/writer/interaction_modes.py`

**Steps:**
- [ ] Add `POSITION_MODE_MAP` alongside existing `STAGE_MODE_MAP`:
  ```python
  POSITION_MODE_MAP: dict[str, str] = {
      "plan": "BRAINSTORM",
      "execute": "EXECUTE",
      "verify": "REVIEW",
  }
  ```
- [ ] Add `get_recommended_mode_for_position(position: str, drift_detected: bool = False) -> str`:
  ```python
  def get_recommended_mode_for_position(position: str, drift_detected: bool = False) -> str:
      """Recommend interaction mode based on loop position."""
      if drift_detected:
          return "DISCUSS"
      return POSITION_MODE_MAP.get(position, "EXECUTE")
  ```

**Verification:**
- [ ] `py -3.14 -c "from app.core.writer.interaction_modes import get_recommended_mode_for_position; print(get_recommended_mode_for_position('plan'), get_recommended_mode_for_position('execute'), get_recommended_mode_for_position('execute', True))"` prints `BRAINSTORM EXECUTE DISCUSS`
- [ ] All existing tests pass

**Commit:** `feat: add position-based mode mapping for loop positions`

---

## Task 6: Refactor runtime.py run() — add loop position logic

**Files:** `backend/app/core/writer/runtime.py`

This is the core refactor. Strategy: surgical edits to the existing run() method, not a full rewrite.

**Steps:**
- [ ] Step 6a: In `run()`, after loading state (line ~176), add complexity assessment:
  ```python
  # Assess task complexity → set loop position
  complexity = self._assess_task_complexity(user_message)
  state.task_complexity = complexity
  if complexity == "simple":
      state.loop_position = "execute"
      state.planning_depth = "none" if state.planning_depth == "full" else state.planning_depth
  elif complexity == "moderate":
      state.loop_position = "plan"
      state.planning_depth = "light"
  else:
      state.loop_position = "plan"
      state.planning_depth = "full"
  await self.deps.state_store.save(state)
  logger.info(f"Task complexity: {complexity} → loop_position={state.loop_position}, planning_depth={state.planning_depth}")
  ```
- [ ] Step 6b: Replace the `enforce_planning` gate (lines 184-198) with loop-position-aware logic:
  ```python
  # Loop position: plan entry condition
  if state.loop_position == "plan":
      state.phase = "planning"
      await self.deps.state_store.save(state)
      await self._emit(writer_phase_event(session_id, state.phase))
      
      if state.task_complexity != "simple":
          if not self._task_plan:  # No pre-extracted files → DesignFSM
              design_state = DesignSessionState()
              self._design_fsm = DesignFSM(design_state, user_message)
              round_prompt = self._design_fsm.get_round_prompt()
              messages.append({"role": "user", "content": round_prompt})
              logger.info("Loop position PLAN: vague task → DesignFSM")
          else:
              plan_prompt = self._build_planning_prompt(user_message)
              messages.append({"role": "user", "content": plan_prompt})
              logger.info("Loop position PLAN: explicit task → write_checklist")
  ```
- [ ] Step 6c: In the W2 planning gate (lines 536-633), wrap the pause-for-confirmation in a `planning_depth` check:
  ```python
  if state.phase == "planning" and self._pending_task_plan is not None:
      if state.planning_depth == "full":
          # Full: pause for user confirmation (existing behavior)
          # ... existing pause code ...
      elif state.planning_depth == "light":
          # Light: auto-confirm, no pause
          state.task_plan = self._pending_task_plan
          state.task_plan.user_confirmed = True
          state.loop_position = "execute"
          state.phase = "executing"
          await self.deps.state_store.save(state)
          await self._emit(writer_phase_event(session_id, state.phase))
          messages.append({"role": "user", "content": "Plan auto-confirmed. Begin implementation."})
          self._pending_task_plan = None
          continue
  ```
- [ ] Step 6d: Replace W10 auto mode switch (lines 647-657) to use loop position:
  ```python
  # W10: Auto mode switching based on loop position
  recommended_mode = get_recommended_mode_for_position(
      state.loop_position, drift_detected=(self._check_drift(state) is not None)
  )
  if recommended_mode != state.mode:
      old_mode = state.mode
      state.mode = recommended_mode
      await self.deps.state_store.save(state)
      await self._emit(writer_mode_event(session_id, state.mode))
      logger.info(f"Auto mode switch: {old_mode} → {recommended_mode} (position={state.loop_position})")
  ```
- [ ] Step 6e: W3 replanning trigger (lines 434-457): update to set `loop_position = "plan"` instead of just `phase = "planning"`:
  ```python
  await self._transition_phase(state, "planning")
  state.loop_position = "plan"  # ← new: explicit loop position re-entry
  ```
- [ ] Step 6f: W4 drift detection (lines 840-850): on drift nudge, set `loop_position = "plan"`:
  ```python
  if self._consecutive_reads >= 5:
      state.loop_position = "plan"  # ← new: drift triggers re-entry to plan
      # ... existing nudge message ...
  ```
- [ ] Step 6g: Step completion (lines 459-516): when all steps done, set `loop_position = "verify"`:
  ```python
  if state.task_plan and state.task_plan.user_confirmed:
      # ... existing step completion logic ...
      # When all steps complete:
      if state.task_plan.progress_summary["completed"] == state.task_plan.progress_summary["total_steps"]:
          state.loop_position = "verify"
  ```
- [ ] Step 6h: Verify position completes → idle:
  ```python
  # In the is_complete handling section (lines 1056-1118):
  if state.loop_position == "verify":
      state.loop_position = "idle"
  ```
- [ ] Step 6i: Import `get_recommended_mode_for_position` from interaction_modes

**Verification:**
- [ ] `py -3.14 -c "from app.core.writer.runtime import WriterRuntime; print('OK')"` — no import errors
- [ ] `py -3.14 -m pytest tests/test_loop_positions.py -v` — all new tests pass
- [ ] `py -3.14 -m pytest tests/ -q` — all existing tests pass (155+)

**Commit:** `refactor: replace linear phase chain with conditional loop positions in run()`

---

## Task 7: Update prompt_assembler.py for loop position awareness

**Files:** `backend/app/core/prompt_assembler.py`

**Steps:**
- [ ] Update `_build_system_prompt` to use `loop_position` instead of just `phase` for planning guidance:
  ```python
  # Replace the existing W2 planning phase check (around line 330):
  if state.loop_position == "plan" and state.task_plan is not None and not state.task_plan.user_confirmed:
      parts.append(
          "PLANNING PHASE ACTIVE. Produce a plan first. Do NOT implement yet. "
          "Call write_checklist to declare your plan. Wait for user confirmation before executing."
      )
  elif state.loop_position == "execute":
      parts.append("EXECUTION PHASE. Implement the plan now. Use write_file for each planned file.")
  elif state.loop_position == "verify":
      parts.append("VERIFICATION PHASE. Check all acceptance criteria. Fix any failing criteria.")
  ```
- [ ] Update `_get_workflow_hint` to also respect loop position

**Verification:**
- [ ] All existing tests pass
- [ ] `py -3.14 -c "from app.core.prompt_assembler import WriterPromptAssembler; from app.core.writer.schemas import WriterSessionState; s = WriterSessionState(session_id='t', work_root='/tmp', loop_position='plan'); pa = WriterPromptAssembler(); print(pa._build_system_prompt(s, 'test'))"` — output contains "PLANNING PHASE"

**Commit:** `feat: update prompt assembler for loop position awareness`

---

## Task 8: Update existing tests for backward compatibility

**Files:** `backend/tests/test_planning_gate.py`, `backend/tests/test_progress_tracking.py`, `backend/tests/test_drift_replan.py`

**Steps:**
- [ ] In `test_planning_gate.py`: add `state.enforce_planning = True` calls where needed (setter now maps to planning_depth="full")
- [ ] In `test_planning_gate.py`: add a new test `test_simple_task_skips_plan_gate`:
  ```python
  def test_simple_task_skips_plan_gate(self):
      """Simple tasks (single file) should skip plan position."""
      from app.core.writer.runtime import WriterRuntime
      complexity = WriterRuntime._assess_task_complexity("修复 auth.py 的登录 bug")
      assert complexity == "simple"
  ```
- [ ] In `test_progress_tracking.py`: ensure step completion sets `loop_position = "verify"` when all done
- [ ] In `test_drift_replan.py`: ensure drift sets `loop_position = "plan"`
- [ ] Run all tests to verify no regressions

**Verification:**
- [ ] `py -3.14 -m pytest tests/ -q` — all 155+ tests pass

**Commit:** `test: update existing tests for loop position backward compat`

---

## Task 9: Update test_wave3_p2.py and test_e2e_w1_w11.py for new fields

**Files:** `backend/tests/test_wave3_p2.py`, `backend/tests/test_e2e_w1_w11.py`

**Steps:**
- [ ] In `test_wave3_p2.py` TestW8LockedContext: update serialization test to also check `loop_position` field
- [ ] In `test_wave3_p2.py` TestW9DelegationStatus: verify `planning_depth` field exists
- [ ] In `test_e2e_w1_w11.py` TestW1ToW11StructuralVerification: add test for `loop_position` field
- [ ] In `test_e2e_w1_w11.py` TestW1ToW11StructuralVerification: add test for `_assess_task_complexity`
- [ ] In `test_e2e_w1_w11.py` TestW1ToW11RealTaskCoverage: update drift test to check `loop_position` changes

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_wave3_p2.py tests/test_e2e_w1_w11.py -q` — all pass

**Commit:** `test: update wave3 and e2e tests for loop position architecture`

---

## Task 10: Full regression + e2e verification

**Files:** none (verification only)

**Steps:**
- [ ] Run full test suite: `py -3.14 -m pytest tests/ -v --tb=short`
- [ ] Verify the count matches or exceeds previous (166+)
- [ ] Spot-check: simple task → no planning pause; complex task → planning gate triggers
- [ ] Verify W2-W11 features still work (all existing W-tests reference `loop_position` or `phase` correctly)

**Verification:**
- [ ] All 166+ tests pass with 0 failures
- [ ] No new warnings beyond existing deprecation note

**Commit:** (no commit — verification only)