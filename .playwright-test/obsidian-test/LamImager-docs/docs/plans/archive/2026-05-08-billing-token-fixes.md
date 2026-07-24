# Billing Token Fixes - Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Architecture:** Add session_id to PromptOptimizeRequest schema; propagate it through optimize_prompt, optimize_prompt_stream, and _describe_reference_images. Extract token usage from chat_edit API responses. Unify all BillingRecord creation through record_billing() helper.

**Tech Stack:** Python 3.14+, FastAPI, SQLAlchemy (async), Pydantic

---

## Task 1: Add session_id to PromptOptimizeRequest schema

**Files:** `backend/app/schemas/prompt.py`

**Steps:**
- [ ] Add `session_id: str | None = None` field to `PromptOptimizeRequest` class (after `multimodal_context`)

**Verification:**
- [ ] `cd backend && python -c "from app.schemas.prompt import PromptOptimizeRequest; r = PromptOptimizeRequest(prompt='test', direction='', llm_provider_id='x', session_id='abc'); print(r.session_id)"` prints `abc`

---

## Task 2: Refactor prompt_optimizer.py — use record_billing + pass session_id

**Files:** `backend/app/services/prompt_optimizer.py`

**Steps:**
- [ ] Replace import: `from app.models.billing import BillingRecord, BillingRecordType` → `from app.models.billing import BillingRecordType`
- [ ] Add import: `from app.services.billing_service import record_billing`
- [ ] In `stream_llm_chat()` (line 54-63): replace `billing = BillingRecord(...)` through `await db.commit()` with:
  ```python
  await record_billing(db, session_id=session_id, provider_id=provider.id,
      billing_type="per_token", tokens_in=tokens_in, tokens_out=tokens_out,
      cost=cost, currency=provider.currency,
      detail={"type": "llm_stream"})
  ```
- [ ] In `optimize_prompt()` (line 191-201): same replacement, also pass `session_id=data.session_id`, and `billing_type="per_token"` (string, not enum)
- [ ] In `optimize_prompt_stream()` (line 245-255): same replacement, pass `session_id=data.session_id`

**Verification:**
- [ ] `cd backend && python -c "from app.services.prompt_optimizer import optimize_prompt, optimize_prompt_stream, stream_llm_chat; print('imports OK')"` — no ImportError

---

## Task 3: Pass session_id from handle_generate to optimize_prompt

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] In `handle_generate()` at line 83-88, add `session_id=session_id` to the `PromptOptimizeRequest(...)` constructor

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import handle_generate; print('imports OK')"`

---

## Task 4: Add session_id to _describe_reference_images + use record_billing

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] Add `session_id: str` parameter to `_describe_reference_images()` signature (line 213)
- [ ] Replace lines 252-262 (BillingRecord creation) with:
  ```python
  await record_billing(db, session_id=session_id, provider_id=provider.id,
      billing_type="per_token", tokens_in=tokens_in, tokens_out=tokens_out,
      cost=cost, currency=provider.currency,
      detail={"type": "image_description", "image_count": len(reference_images)})
  ```
- [ ] In `_apply_vision_fallback()` at line 415, pass `session_id` to `_describe_reference_images(db, llm_provider_id, reference_images, session_id)`

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import handle_generate; print('imports OK')"`

---

## Task 5: Extract token usage from chat_edit responses

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] In `_generate_with_references()`, add parameter `chat_edit_tokens: dict` (a mutable dict accumulator) after `semaphore`
- [ ] After the first `client.chat_edit()` call (line 286-292), extract usage:
  ```python
  usage = response.get("usage", {})
  chat_edit_tokens["tokens_in"] = chat_edit_tokens.get("tokens_in", 0) + usage.get("prompt_tokens", 0)
  chat_edit_tokens["tokens_out"] = chat_edit_tokens.get("tokens_out", 0) + usage.get("completion_tokens", 0)
  ```
- [ ] In the `chat_edit_one()` inner function (line 301-312), after extracting urls, also extract usage and add to `chat_edit_tokens`
- [ ] In `handle_generate()` line 138-143, create `chat_edit_usage = {}` and pass it:
  ```python
  result = await _generate_with_references(
      db, session_id, client, provider, prompt, data, all_image_urls, semaphore, chat_edit_usage
  )
  ```
- [ ] After line 163, compute cost differently when chat_edit tokens are available:
  ```python
  if chat_edit_usage:
      tokens_in = chat_edit_usage.get("tokens_in", 0)
      tokens_out = chat_edit_usage.get("tokens_out", 0)
      if provider.billing_type.value == "per_token" and provider.unit_price:
          cost = float(provider.unit_price) * (tokens_in + tokens_out) / 1000
      else:
          cost = _compute_cost(provider, data.image_count)
  else:
      tokens_in = 0
      tokens_out = 0
      cost = _compute_cost(provider, data.image_count)
  ```
- [ ] Add imports at top: `from app.services.billing_service import record_billing`

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import handle_generate; print('imports OK')"`

---

## Task 6: Refactor main billing in handle_generate to use record_billing

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] Remove `from app.models.billing import BillingRecord, BillingRecordType` from imports (keep only `BillingRecordType` if still needed)
- [ ] Replace lines 166-175 (main BillingRecord creation) with:
  ```python
  await record_billing(db, session_id=session_id, provider_id=provider.id,
      billing_type=provider.billing_type.value,
      tokens_in=tokens_in, tokens_out=tokens_out,
      cost=cost, currency=provider.currency,
      detail={"prompt": prompt, "image_count": data.image_count, "image_size": data.image_size})
  ```
  (Note: `tokens_in`/`tokens_out` variables come from Task 5 above)

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import handle_generate; print('imports OK')"`
- [ ] `cd backend && grep -l "BillingRecord(" app/services/generate_service.py app/services/prompt_optimizer.py` should return NO matches (no more direct construction)

---

## Task 7: End-to-end verification

**Steps:**
- [ ] Run backend import check: `cd backend && python -c "from app.main import app; print('backend imports OK')"`
- [ ] Verify no direct `BillingRecord(` construction remains: `cd backend && rg 'BillingRecord\(' app/services/` should return 0 matches
- [ ] Check frontend builds: `cd frontend && npm run build` (should succeed, no frontend changes)

**Verification:**
- [ ] All checks pass
