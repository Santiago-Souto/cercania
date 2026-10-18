# Deploy (Render)

Both services deploy from `main` through the Render Blueprint in `render.yaml`. A push to `main` redeploys them.

## URLs

| Service | URL | Notes |
|---|---|---|
| API (`cercania-api`) | https://cercania-api.onrender.com | FastAPI. Health check: [`/health`](https://cercania-api.onrender.com/health) returns `{"status":"ok","service":"cercania-api"}` |
| Web (`cercania-web`) | https://cercania-web.onrender.com | Next.js. Starts at [`/login`](https://cercania-web.onrender.com/login) |

## Current state

- **The web reads the real API** with a real login (6-digit SMS code, CIA-32 / CIA-14). There is no fake data anymore. The browser calls `/api/*` on the web, which Next.js rewrites to `NEXT_PUBLIC_API_URL`, so the session cookie is first-party on the web origin. `NEXT_PUBLIC_*` values and the rewrite are fixed at build time: change them, then redeploy the web.
- Keep `ALLOW_DEV_IDENTITY_HEADER` unset on the API (the web never sends `X-Person-Id`).
- **Free plan: both services sleep** after ~15 minutes idle, and the first request then takes about a minute. The GitHub Action `.github/workflows/keep-awake.yml` pings `https://cercania-web.onrender.com/api/health` every 5 minutes from 09:00 to 19:55 Argentina time; that one request reaches both services (the web's `/api/*` rewrite forwards it to the API). Outside that window they sleep, and GitHub can start scheduled runs late or skip them, so still open both URLs a minute before a demo. Budget: the workspace gets 750 free instance hours a month, shared by both services. Awake all day, the two use 48 hours a day and run out in about 15 days, after which Render suspends them until next month. The daytime window uses about 23 hours a day (~700 a month), leaving little room for traffic outside it: do not widen the window without upgrading a service. Run it by hand with "Run workflow" in the Actions tab.

## Environment variables

Secrets live only in Render (service -> Environment). Never commit them. The full list, with comments, is in `render.yaml` and `.env.example`.

| Service | Variables |
|---|---|
| API | `DATABASE_URL` (Supabase session pooler), `GROQ_API_KEY` (transcription, extraction, triage and cited query), optional `ANTHROPIC_API_KEY`, `EXTRACT_MODEL` / `TRIAGE_MODEL` / `QUERY_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` to switch LLM vendor, `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_BUCKET` (voice notes; private bucket `media`, service key backend only: legacy `service_role` JWT or new `sb_secret_` key), `PUBLIC_BASE_URL` (= the API URL), `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (login code by SMS), `TWILIO_TRIAL_TEMPLATE=sms_2fa` while the Twilio account is a trial (simulated security, see README), `WEB_ORIGINS` (= the web URL), `SESSION_COOKIE_SAMESITE=lax` (the cookie is first-party through the web's `/api` rewrite), `ALLOW_DEV_IDENTITY_HEADER` (backend dev fallback; leave unset in the deploy) |
| Web | `NEXT_PUBLIC_API_URL` (= the API URL; used by server components and by the `/api/*` rewrite) |

## Troubleshooting

- **The API answers 502 or takes a long time:** it is waking up. Wait about a minute and retry `/health`.
- **Login works but every screen sends you back to `/login`:** the session cookie is not reaching the API. Check that the browser calls go to `/api/...` on the web host (not the API host) and that the web was redeployed after changing `NEXT_PUBLIC_API_URL`.
- **The web shows "No pudimos conectar con el servidor":** check `NEXT_PUBLIC_API_URL` on the web service and that the API's `/health` responds.
- **A report does not go through:** check the API logs for the `POST /patients/{id}/reports` request (transcription needs `GROQ_API_KEY`).
