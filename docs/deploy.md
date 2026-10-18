# Deploy (Render)

Both services deploy from `main` through the Render Blueprint in `render.yaml`. A push to `main` redeploys them.

## URLs

| Service | URL | Notes |
|---|---|---|
| API (`cercania-api`) | https://cercania-api.onrender.com | FastAPI. Health check: [`/health`](https://cercania-api.onrender.com/health) returns `{"status":"ok","service":"cercania-api"}` |
| WhatsApp webhook | https://cercania-api.onrender.com/webhook/whatsapp | Registered with Meta by `backend/scripts/setup_whatsapp.py` (see `docs/whatsapp-setup.md`) |
| Web (`cercania-web`) | https://cercania-web.onrender.com | Next.js. Starts at [`/login`](https://cercania-web.onrender.com/login) |

## Current state

- **The web shows fictional fake data** (`NEXT_PUBLIC_USE_FAKE_DATA=1`, with a "Datos de prueba ficticios" banner) until the API has read endpoints (CIA-14). To switch, set it to `0` in Render and redeploy the web. `NEXT_PUBLIC_*` values are fixed at build time, so changing them in Render does nothing without a redeploy.
- **Free plan: both services sleep** after ~15 minutes idle, and the first request then takes about a minute. Open both URLs a minute before a demo.

## Environment variables

Secrets live only in Render (service -> Environment). Never commit them. The full list, with comments, is in `render.yaml` and `.env.example`.

| Service | Variables |
|---|---|
| API | `DATABASE_URL` (Supabase session pooler), `GROQ_API_KEY` (transcription, extraction, triage and cited query), optional `ANTHROPIC_API_KEY`, `EXTRACT_MODEL` / `TRIAGE_MODEL` / `QUERY_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` to switch LLM vendor, `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_BUCKET` (voice notes; private bucket `media`, service key backend only: legacy `service_role` JWT or new `sb_secret_` key), `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `PUBLIC_BASE_URL` (= the API URL), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (login code by SMS), `TWILIO_TRIAL_TEMPLATE=sms_2fa` while the Twilio account is a trial (simulated security, see README), `WEB_ORIGINS` (= the web URL; the session cookie needs it), `ALLOW_DEV_IDENTITY_HEADER` (simulated identity; `1` only with fictional data) |
| Web | `NEXT_PUBLIC_API_URL` (= the API URL; read at **build** time too: `next.config.ts` proxies `/api/*` to it, so changing it needs a redeploy), `NEXT_PUBLIC_USE_FAKE_DATA`, `NEXT_PUBLIC_DEV_PERSON_ID` (simulated identity sent as `X-Person-Id`; only with `ALLOW_DEV_IDENTITY_HEADER=1` and fictional data) |

## Troubleshooting

- **The API answers 502 or takes a long time:** it is waking up. Wait about a minute and retry `/health`.
- **The web shows "No pudimos conectar con el servidor":** check `NEXT_PUBLIC_API_URL` on the web service and that the API's `/health` responds.
- **Login works but every screen sends you back to `/login`:** the browser must reach the API through the web's `/api/*` proxy. Check that `NEXT_PUBLIC_API_URL` was set when the web was built, and that `/api/health` on the web URL answers.
- **No WhatsApp messages arrive:** see the troubleshooting section in `docs/whatsapp-setup.md`.
