# __MEMBER_NAME__

> __MEMBER_NAME__ member of LamTools

## Rules

- Follow existing project patterns; never impose personal preferences.
- Run tests after every change that could break something.
- Communicate with the user in English.

## Dev Commands

```bash
cd backend && py -3.14 -m uvicorn app.main:app --reload --port __BACKEND_PORT__
cd frontend && npm run dev
```

## Architecture

- Backend: FastAPI + lamtools_core
- Frontend: Vue3 + @lamtools/ui
- Member-specific policy belongs in `backend/app/member/`.
- Do not add product-local runtime, provider parser, SSE manager, or duplicate Core event/session logic.
