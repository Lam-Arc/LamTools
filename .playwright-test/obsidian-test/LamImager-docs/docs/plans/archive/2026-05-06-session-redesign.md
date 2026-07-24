# LamImager Session UI Redesign

> **Status: COMPLETED** (2026-05-07)

## Goal
Redesign LamImager from a form-based task manager to a conversation-based interaction model with session windows, LLM assistant sidebar, and integrated skill/rule/optimization/planning features.

## Key Design Decisions

1. **Conversation-based sessions** instead of form-based task creation
2. **Sidebar + chat area** layout (like ChatGPT)
3. **LLM assistant sidebar** with 4 tabs: Dialog, Optimize, Plan, Skills
4. **Context sharing toggle** in dialog tab (shared context vs current input only)
5. **Multi-select optimization directions** + custom instruction support
6. **Default model selectors** in API management page
7. **Chinese interface** by default

## New Data Models

### sessions
- id (UUID PK), title, created_at, updated_at

### messages
- id (UUID PK), session_id (FK), role (user/assistant/system)
- content (TEXT), message_type (text/image/plan/optimization/skill)
- metadata (JSON), created_at

### app_settings
- id (UUID PK), key (VARCHAR), value (JSON), updated_at
  - default_optimize_provider_id
  - default_image_provider_id
  - default_plan_provider_id

## UI Structure

### Session Page (/sessions, default home)
- Left: Session list (220px) with title, progress bar, cost/token
- Center: Chat area with message flow + input area
- Right: LLM assistant sidebar (360px, collapsible) with 4 tabs

### API Management Page (/api-manage)
- Top: Default model configuration (3 selectors)
- Bottom: Provider table (unchanged)

### Other pages
- Skills, Rules, References, Settings - keep existing design, translate to Chinese

## Skill/Rule Call Chain

1. User input → Skill application (optional, manual selection)
2. → Rule application (automatic, global, by priority)
3. → Prompt optimization (optional, manual trigger)
4. → Task planning (optional, manual trigger)
5. → Image generation (parallel API calls)
6. → Auto billing record

## Navigation (Chinese)
- 概览, 会话, API管理, 技能, 规则, 参考图, 设置
