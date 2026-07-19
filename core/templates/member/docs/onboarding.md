# __MEMBER_NAME__ — Member Onboarding

## Quick Start

1. Shared UI, from the repository root: `npm.cmd install --prefix core/ui`, then `npm.cmd run build --prefix core/ui`.
2. Backend: `cd backend`, then `py -3.14 -m uvicorn app.main:app --reload --port __BACKEND_PORT__`.
3. Frontend: `cd frontend`, then `npm.cmd install` and `npm.cmd run dev`.
4. Open http://localhost:__FRONTEND_PORT__

## Core Integration

- Backend uses `lamtools_core.app.create_app` with `backend/app/member/manifest.py`
- Member domain material starts in `backend/app/member/kit.py`, `prompts.py`, `tools.py`, and `verification.py`
- Frontend uses `@lamtools/ui` components (WorkspaceShell, SessionSidebar, ChatThread, ComposerBar)
- Core routes enabled at `/api/core`

## Next Steps

- [ ] Fill `backend/app/member/prompts.py` with product persona and policy
- [ ] Add product tool specs to `backend/app/member/tools.py`
- [ ] Adjust `backend/app/member/verification.py` for product acceptance rules
- [ ] Add business routers to `backend/app/routers/`
- [ ] Fill WorkspaceShell slots with product-specific UI
