<!-- 历史参考，不代表当前架构 -->
<!-- 维护标注（2026-07-08）：本文记录 2026-05-30 的旧运行时验收设计。当前 Writer 已删除 `CompletionVerifier` 自研自动完成验收层；普通任务不再在自然最终回复后自动跑语法/浏览器/产物扫描。若后续需要语法或构建检查，应由用户或任务 prompt 显式要求模型调用工具执行。 -->
# Writer Known Defects — 2026-05-30

This checkpoint changes completion from a Writer self-declaration into a
runtime-owned verification gate. A generated project is not allowed to emit
`writer_done` unless `CompletionVerifier` passes.

## Fixed in this checkpoint

- `DesignAgent` no longer silently degrades timed-out rounds into usable design:
  low/high/max idle round timeouts are 120s/180s/240s, transient provider errors
  retry every 2s up to 30 times, and exhausted retries/round hard caps produce
  invalid design handoff instead of a normal design.
- `WriterRuntime` treats `turn.is_complete` as candidate completion only.
  Runtime verification now gates `writer_done`; failed verification injects a
  repair prompt; exhausted repair emits `writer_failed`.
- CLI and frontend now surface `writer_failed`,
  `writer_verification_started`, and `writer_verification_completed`.
- Implicit vague app/software tasks are forced toward a zero-install local MVP:
  no PyQt/PySide/Qt, Electron/Tauri/Vite/React/Vue/Svelte, Rust/Cargo,
  Flask/FastAPI/Django/SQLAlchemy/Werkzeug, Pillow/PIL, NumPy, OpenCV/cv2,
  CDN scripts, or remote WASM unless the user explicitly asks for that stack.
- `CompletionVerifier` checks runnable artifacts, dependency/import scans,
  Python `compileall`, Python non-test module import smoke, pytest, local
  HTML references, local JavaScript imports, and JavaScript syntax when Node is
  available.
- `edit_file` rejects empty `old_string`; this now becomes a real tool error,
  not a successful no-op.
- Repair prompts now direct Writer to align source/test APIs coherently and use
  `write_file` for whole-file rewrites when exact edit anchors are unavailable.
- Recoverable write/edit failures stay on the current plan step instead of
  skipping that deliverable.
- Plan progress now requires `_deliverable_ready`; empty files and real stubs no
  longer count as completed deliverables.
- When the final planned deliverable is written, `WriterRuntime` now runs
  `CompletionVerifier` immediately after the tool turn. It no longer lets the
  LLM spend extra verify-mode turns doing manual spot-check reads/searches before
  the runtime-owned gate.

## Remaining defects

- `DesignAgent` can still produce heavy architecture ideas for vague local app
  tasks. Runtime scope gates usually pull implementation back to stdlib/Tkinter,
  but the handoff can remain noisy.
- The implementation loop is still slow on broad vague app tasks: it often emits
  one or two files per turn and may read several files before continuing.
- Main runtime LLM calls can still time out after plan confirmation. This
  checkpoint raises the main-call timeout to 360s, allows four timeout recovery
  attempts, strips context after timeout, and forces the recovery prompt down to
  one file per turn, but this path still needs another full E2E pass.
- Repair behavior is improved but not proven fully convergent on every generated
  interface mismatch. Current policy is intentionally strict: failure to repair
  must end in `writer_failed`, not fake completion.
- Generated tests may still be poor contracts. Runtime can run and enforce them,
  but it does not yet synthesize an independent oracle for whether generated
  tests are semantically sufficient.
- The current frontend only surfaces the new verification/failure states. Full
  Writer UI/UX redesign remains separate work after backend reliability is
  stable.

## E2E status

- `video_editor_final_rerun7_20260530_1158`: no false `writer_done`, but timed
  out after 2400s in repair. Root causes observed: in-band edit rejections were
  treated as completed tools, repair spent too long reading, and failed writes
  could be skipped by the plan.
- `video_editor_repair_gate_20260530_124510`: invalidated manually during run.
  It proved that recoverable write rejection (`ui/preview.py` using PIL) was
  marked as a failed step and that a 0-byte `ui/timeline.py` could advance
  progress. Both issues are fixed in this checkpoint.
- `video_editor_final_gate_20260530_130604`: invalidated manually. It showed
  that asking for 3-5 files per turn made main implementation responses too
  large/slow.
- `video_editor_final_gate2_20260530_132237`: failed correctly with
  `writer_failed: llm_error`, not false completion. Root cause was two
  consecutive 240s main-loop LLM timeouts immediately after plan confirmation.
  Follow-up fix in this checkpoint raises the timeout/recovery budget and
  reduces implementation batch size, but a new full E2E run is still required.
- `video_editor_latest_20260530_143701`: invalidated manually after all 11
  planned files were generated. Root cause: after the last deliverable,
  verify-mode kept asking the LLM to run `verify_design`, `search_content`, and
  `read_file` spot-checks instead of immediately running `CompletionVerifier`.
  Fixed by triggering the runtime verifier directly after the tool turn that
  completes all planned deliverables.
