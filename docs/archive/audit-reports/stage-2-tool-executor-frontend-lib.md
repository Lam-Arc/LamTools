<!-- 历史参考，不代表当前架构 -->
# Stage 2: Tool Executor & Frontend Lib Extraction

## Summary
Extracted 8 low-risk tools from `runtime.py` into `tool_executor.py` module; extracted shared frontend types/constants/formatters into `lib/` modules. No new features, no behavior changes.

## Backend Changes

### New Files
- `members/writer/backend/app/core/writer/tool_executor.py` - `ToolExecutor` class with 8 tool implementations
- `members/writer/backend/tests/test_tool_executor.py` - 42 tests covering all extracted tools

### Modified Files
- `members/writer/backend/app/core/writer/runtime.py` - Delegates to `ToolExecutor` for 8 tools; removed ~300 lines of inline implementations

### Extracted Tools (Low-Risk Only)
1. `read_file` - File reading with truncation
2. `write_file` - File writing with parent dir creation
3. `edit_file` - String replacement editing
4. `search_content` - Regex content search
5. `search_files` - Glob file pattern search
6. `list_dir` - Directory listing
7. `git_status` - Git status (delegates to git_context)
8. `git_diff` - Git diff (delegates to git_context)

### Delegation Pattern
```python
# runtime.py _run_tool
result = await self._tool_executor.execute(tool_name, params, ...)
if result is not None:
    return result
# Fall through to existing elif chain for unhandled tools
```

### Deferred Tools (High-Risk, NOT Split)
- `run_command` - Shell execution, security-sensitive
- `run_tests` - Test runner, complex state
- `*_agent` - Agent-as-tool delegation, runtime state
- `architecture_agent` - Architecture agent, complex flow
- `mcp_tool` - MCP integration, external deps

### Helper Methods Delegated
- `_resolve_path` → `tool_executor.resolve_path`
- `_validate_path` → `tool_executor.validate_path`
- `_read_file` → `tool_executor.read_file`
- `_write_file` → `tool_executor.write_file`
- `_edit_file` → `tool_executor.edit_file`
- `_search_content` → `tool_executor.search_content`
- `_search_files` → `tool_executor.search_files`
- `_git_status` → `tool_executor.git_status`
- `_git_diff` → `tool_executor.git_diff`
- `_list_dir` → `tool_executor.list_dir`
- `_truncate_tool_output` → `tool_executor.truncate_tool_output`
- `_filter_command_output` → `tool_executor.filter_command_output`
- `_file_identity_keys` → `tool_executor.file_identity_keys`

### Kept in Runtime (Instance State Access)
- `_mark_file_read` - Uses `self._file_read_counts`
- `_can_mutate_existing_file` - Uses `self._created_files`

## Frontend Changes

### New Files
- `members/writer/frontend/src/lib/theme.ts` - ThemeStop type, defaultTheme, color/gradient helpers
- `members/writer/frontend/src/lib/labels.ts` - Status/phase/tool label functions, activity group metadata
- `members/writer/frontend/src/lib/runtime-types.ts` - 20 extracted types from WorkbenchView

### Modified Files
- `members/writer/frontend/src/views/WorkbenchView.vue` - Imports from lib/, removed ~400 lines
- `members/writer/frontend/src/views/SettingsView.vue` - Imports from lib/theme, removed ~80 lines

### Extracted to lib/theme.ts
- `ThemeStop` type
- `defaultTheme` constant
- `normalizeColor`, `clampNumber`, `normalizeGradientStops`
- `gradientFromStops`, `rgbaFromHex`, `hexToRgb`

### Extracted to lib/labels.ts
- `RuntimeActivityGroup` type
- `statusLabel`, `phaseLabel`, `stepKindLabel`, `runtimeTextLabel`
- `formatTime`, `shortSha`, `formatDurationMs`
- `stringValue`, `normalizeMessageText`, `numberValue`, `businessText`
- `isTechnicalNoise`, `technicalReasonLabel`, `workflowPhaseLabel`
- `localizeStatusWords`, `activityGroupMeta`, `activityGroupOrder`

### Extracted to lib/runtime-types.ts
- `RuntimeBlock`, `AgentSummary`, `AgentProgressLine`, `AgentLogView`
- `ProjectGroup`, `ProjectSessionMode`, `ReviewMode`
- `DecisionView`, `DecisionPlanStepView`, `DecisionPlanView`
- `ActivityGroupView`, `LifecycleView`, `PlanProgressView`
- `ReplyAttachmentPreview`, `RuntimeGroup`, `TranscriptItem`
- `DiffRow`, `DiffBlock`, `DiffFileView`

### Kept in Components (State-Dependent)
- `sessionStatusLabel` (WorkbenchView) - References component reactive state
- `summarizeDetails` (WorkbenchView) - References component reactive state
- `gradientFromTheme` (SettingsView) - Simple wrapper around imported `gradientFromStops`

## Verification Results

### Frontend Builds
- ✅ `core/ui` - 23 modules, built in 131ms
- ✅ `members/writer/frontend` - 72 modules, built in 729ms
- ✅ `members/artist/frontend` - 1505 modules, built in 1.53s

### Backend Tests
- ✅ `test_tool_executor.py` - 42 passed, 2 skipped
- ✅ Writer backend tests - 274 passed
- ✅ Core tests - 372 passed

### Legacy Scan
- ✅ No dual-track patterns found (LAMWRITER_CORE_KERNEL, etc.)

## Next Priorities

1. **Continue tool extraction** - Consider extracting medium-risk tools:
   - `web_fetch`, `web_search` - HTTP operations
   - `recall_session`, `load_skill` - Session/skill management
   - `inspect_project`, `browser_check` - Project inspection

2. **Frontend component extraction** - Consider extracting from WorkbenchView:
   - `AgentCard` component
   - `DecisionCard` component
   - `GitPanel` component
   - `ActivityGroup` component

3. **Artist alignment** - Apply same extraction pattern to Artist runtime.py

4. **High-risk tool review** - Plan safe extraction of:
   - `run_command` with proper sandboxing
   - `run_tests` with isolation strategy
   - concrete Agent tools with clear interfaces

## Files Changed Summary
```
 M members/writer/backend/app/core/writer/runtime.py     (-298 lines)
 M members/writer/frontend/src/views/SettingsView.vue    (-80 lines)
 M members/writer/frontend/src/views/WorkbenchView.vue   (-418 lines)
 + members/writer/backend/app/core/writer/tool_executor.py
 + members/writer/backend/tests/test_tool_executor.py
 + members/writer/frontend/src/lib/theme.ts
 + members/writer/frontend/src/lib/labels.ts
 + members/writer/frontend/src/lib/runtime-types.ts
```
