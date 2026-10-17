# CercanIA web

Next.js 16 (App Router) + shadcn/ui + Tailwind v4. Mobile-first, UI in Spanish.

- Design source of truth: `../docs/design/DESIGN.md` (tokens, screen -> route -> ticket map).
- UI: shadcn components only (`components/ui/`, add more with `npx shadcn@latest add <name>`), themed in `app/globals.css`. CercanIA variants live inside those files (badge, button, alert). Icons: lucide-react.
- App chrome shared by every screen: `components/app/shell.tsx`.
- Data: always through `lib/api.ts` (fake data in `lib/fake.ts` while `NEXT_PUBLIC_USE_FAKE_DATA` is not `0`). Types mirror `../docs/contract.md`.

```bash
npm install
npm run dev
```
