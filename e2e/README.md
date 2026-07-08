# LamTools E2E Tests

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
