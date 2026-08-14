# LamTools E2E Tests

> **⚠️ DEPRECATED（2026-08-13，audit 24 S2）**：本套件已过期，指向已归档的
> Writer 产品（`archive/members/`），不在任何 CI 工作流中运行，且依赖已被移除
> 的产品外壳。请勿在此之上新增用例；重写为 Core（Tauri 观测环境）端到端
> 用例的计划见 `docs/code-audit/24-*.md`，落地前以 `core/tests/` 的
> `test_core_live_client_e2e.py`（真实 WS server）为准。

Playwright E2E smoke tests for the active LamTools frontend.

## Setup

```bash
cd E:\LamTools\e2e
npm install
npx playwright install chromium
```

## Run Smoke Tests

### 1. Start frontend dev servers

Open one terminal:

```bash
# Terminal 1 — Writer frontend (port 6174)
cd E:\LamTools\members\writer\frontend
npm run dev
```

### 2. Run smoke tests

```bash
cd E:\LamTools\e2e
npm run test:smoke
```

Or run the Writer smoke spec directly:

```bash
npx playwright test --project=writer-smoke
```

## Ports

| Frontend | Dev port | Playwright project |
|----------|----------|--------------------|
| Writer   | 6174     | writer-smoke       |

## What smoke tests check

- Page shell loads (body visible)
- Left sidebar drawer exists (`.drawer-left`)
- Brand text in sidebar header (LamWriter)
- Composer textarea exists (`.floating-composer textarea`)
- Main content area exists (`.writer-main`)

Smoke tests do **not** connect to any LLM or test AI functionality.

## Failure policy

Smoke tests fail hard. If the page cannot open, a selector does not exist, or brand text does not match, the test fails. There is no soft failure.
