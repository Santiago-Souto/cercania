# CercanIA web

Next.js 16 (App Router) + shadcn/ui + Tailwind v4. Mobile-first, UI in Spanish.

- Design source of truth: `../docs/design/DESIGN.md` (tokens, screen -> route -> ticket map).
- UI: shadcn components only (`components/ui/`, add more with `npx shadcn@latest add <name>`), themed in `app/globals.css`. CercanIA variants live inside those files (badge, button, alert). Icons: lucide-react.
- App chrome shared by every screen: `components/app/shell.tsx`.
- Data: server components always go through `lib/api.ts`, which forwards the session cookie to the backend at `NEXT_PUBLIC_API_URL`. Browser calls (`lib/client-api.ts`, `lib/send-report.ts`, `lib/auth.ts`) use `/api/*`, rewritten to the backend in `next.config.ts`, so the cookie stays first-party. No session or a `401` -> `/login` (`proxy.ts` and `lib/api.ts`). Types mirror `../docs/contract.md`. There is no fake data: run the backend with the seed data.

```bash
npm install
npm run dev
```

## Install on a phone

The app is installable (no app store): open the URL, then **Compartir → Agregar a inicio** on iPhone or **⋮ → Instalar app** on Android. It opens full screen with the CercanIA icon. There is no service worker on purpose: it is online-only, so every screen loads live data from the backend. Manifest: `app/manifest.ts`; icons: `app/icon.tsx`, `app/apple-icon.tsx`.
