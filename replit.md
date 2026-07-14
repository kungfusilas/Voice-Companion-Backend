# BondAI / LegacyBond

An AI companion app that remembers who you're becoming — voice-first, relationship-aware, and deeply personalized.

The app lives in `artifacts/voice-companion/`: a **Python/FastAPI** backend plus a **Vite/React** frontend that the workspace builds as a pnpm package. The repo root is a pnpm workspace, but the API server is Python, not Node.

## Run & Operate

- **App (Replit):** the `Voice Companion API` workflow runs `python artifacts/voice-companion/run.py` — FastAPI/uvicorn on port **8001** (`app.main:app`). This is the source of truth for how the app boots.
- **Backend deps:** `artifacts/voice-companion/requirements.txt` / `pyproject.toml` (Python 3.11). Installed with `uv`/pip in the Replit image.
- **Frontend build:** from `artifacts/voice-companion/`, `PORT=5000 BASE_PATH=/companion/ pnpm run build` → outputs to `dist/public` (served by FastAPI). Both env vars are **required** by `vite.config.ts` or the build aborts.
- **Frontend dev:** `pnpm --filter @workspace/voice-companion run dev` (Vite, proxies `/companion/api/*` → FastAPI:8001).
- **Typecheck:** `pnpm run typecheck` (root) or `pnpm --filter @workspace/voice-companion run typecheck`.
- **Deploy:** Replit Deployments → GCE, runs `python run.py`. The committed `dist/public` is served as-is — **frontend changes require a `pnpm run build` before Republish**, because deploy does not rebuild the frontend.

## Stack

- **Backend:** Python 3.11, FastAPI + uvicorn (`artifacts/voice-companion/app/`)
- **Frontend:** Vite + React + TypeScript, Tailwind, Radix UI, wouter, TanStack Query (`artifacts/voice-companion/src/`), base path `/companion/`
- **Auth / DB / Storage:** Supabase (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) — Postgres + Auth (JWKS/ES256) + Storage buckets. No Drizzle, no `DATABASE_URL`.
- **Payments:** Stripe (Checkout + Customer Portal + signed webhooks)
- **AI providers:** Anthropic Claude (chat), OpenAI (TTS), Deepgram (STT, WebSocket), ElevenLabs, HeyGen (selfies)
- **Package manager:** pnpm workspaces (frontend only)

## Where things live

- `artifacts/voice-companion/app/` — FastAPI app; `app/main.py` is the ASGI entry; `app/routers/` holds endpoints (`chat.py`, `tts.py`, `stt.py`, `vault.py`, `personas.py`, `entitlements.py`, `payments.py`, `auth.py`).
- `artifacts/voice-companion/app/auth_middleware.py` — `verify_token` (Supabase JWT verifier) used by all authenticated routes.
- `artifacts/voice-companion/src/` — React frontend; `src/App.tsx` is the screen router; `src/pages/` holds screens.
- `artifacts/voice-companion/dist/public/` — committed build output served by FastAPI.
- `artifacts/voice-companion/run.py` — uvicorn launcher (port 8001).

## Architecture decisions

- **Two-process split:** Vite serves the SPA on `PORT` and proxies `/companion/api/*` to FastAPI on 8001. Frontend base path is `/companion/`.
- **Auth is sign-in-only:** all API routes require a Supabase JWT (`verify_token`); there is no guest access.
- **Tiers:** `free` (30 msgs/mo, cheap path — no long-term memory/scoring), plus paid `basic`/`premium`/`power`. Monthly caps live in `entitlements.py` (`PLAN_CAPS`); Stripe webhooks set the plan.
- **Service-role key bypasses RLS:** the backend uses `SUPABASE_SERVICE_KEY` for privileged Storage/DB ops; keep it server-side only.

## Product

Sign-in-required AI companion: users pick a persona and chat (text + voice). Free tier gives a limited monthly allowance; paid tiers unlock persistent memory, relationship progression, higher limits, and richer features. Subscriptions and cancellation run through Stripe.

## Gotchas

- `vite.config.ts` throws unless **both** `PORT` and `BASE_PATH` are set at build time (`BASE_PATH=/companion/`).
- `emptyOutDir: true` — a build wipes and regenerates `dist/public` from `src/` + `public/`; assets only in the old committed `dist` will disappear.
- Deploy runs `python run.py` only — it does **not** build the frontend. Always `pnpm run build` and commit `dist/public` before Republish.
- The Replit **preview pane** ("Your app is not running / Run") is the in-editor dev server, separate from the live **Deployment**. It being idle says nothing about production.

## User preferences

- Wants honest technical assessments, not agreement; verify findings before recommending (no hallucinated fixes).
