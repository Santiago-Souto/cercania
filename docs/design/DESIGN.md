# CercanIA design

Source of truth for the web app's look and screens. Build every screen from this file and the artboards in `screens/`. If the UI needs to change, change the design first (or in the same PR), then the code.

- Live canvas: "CercanIA mobile screens" (Claude artifact, ask Dev B for access). The files in `screens/` are snapshots of it: open them as reference, never import them into the app.
- Mobile-first: designed at 390×844. On desktop the app is the same layout in a centered column, max 480px wide.
- UI copy in Spanish (Río de la Plata: "vos", "contá", "acordate"). All names and data shown are fictional.

## Marca

Logo: **Cercanía**. Dos puntos superpuestos: el verde forma una C que sostiene al punto ámbar (la persona cuidada). La C de Cercanía, y la cercanía como gesto. Mock aprobado: "Logo v8" en el canvas de diseño.

- **Símbolo:** `BrandMark` en `web/components/app/shell.tsx` (círculo verde r26, aro del color de fondo r17, punto ámbar r13, centros a 18 de distancia; viewBox `14 20 72 64`). No deformar, no rotar, no cambiar las proporciones.
- **Logotipo:** "Cercan" en tinta + "ía" en ámbar, Bricolage Grotesque 800, tracking −0.035em. Siempre con tilde.
- **Colores:** verde `#0E5A55` (`--primary`), ámbar `#E39B35` (`--brand-amber`) para el punto y sobre fondo verde. Para el texto "ía" sobre fondos claros, `#B87418` (`--brand-amber-ink`), porque el ámbar claro no llega a 3:1 sobre blanco.
- **Sobre fondo verde:** el círculo pasa a blanco, el aro toma el verde y el punto queda ámbar. Así son los íconos de la app (`app/icon.tsx`, `app/apple-icon.tsx`).
- **Tamaño mínimo:** símbolo de 20 px; logotipo completo de 18 px de alto.
- **Nombre:** el logo dice "Cercanía". En textos de la app y en la documentación el producto sigue figurando como "CercanIA" hasta que el equipo decida unificarlo.

## Tokens

Defined once as CSS variables in `web/app/globals.css`, under shadcn's names where one exists (`--ground` → `--background`, `--ink` → `--foreground`, `--muted` → `--muted-foreground`, `--line` → `--border`, `--field` → `--input`, `--warn-bg` → `--warning`, `--warn-ink` → `--warning-foreground`, `--danger` → `--danger`/`--destructive`). Use them through Tailwind classes (`bg-warning`, `text-muted-foreground`…). Never hardcode a hex in a component.

| Token | Value | Use |
|---|---|---|
| `--ground` | `#F5F6F2` | page background |
| `--surface` | `#FFFFFF` | cards, bars |
| `--ink` | `#16201C` | main text |
| `--ink-2` | `#3C4843` | secondary paragraphs |
| `--muted` | `#4F5B56` | captions, labels (passes 4.5:1 on white and ground) |
| `--line` | `#DDE2DC` | card borders |
| `--line-soft` | `#ECEFEA` | row dividers inside cards |
| `--field` | `#C9D0C9` | input borders |
| `--dashed` | `#7D8783` | dashed "not mentioned" chips |
| `--track` | `#E7EBE6` | progress track, segmented control |
| `--primary` | `#0E5A55` | brand, primary buttons, verified |
| `--primary-hover` | `#0A4440` | hover / pressed |
| `--primary-soft` | `#E3EFEC` | avatars, soft badges |
| `--warn-bg` | `#FBEFD9` | alert chips and cards |
| `--warn-ink` | `#7A4106` | text on `--warn-bg` |
| `--warn-tint` | `#FFF8EC` | unverified quote row |
| `--danger` | `#A61B1B` | red flag, "Necesito ayuda", recording |
| `--danger-soft` | `#FCE8E6` | red flag on family view |
| `--danger-ink` | `#7E1414` | text on `--danger-soft` |
| `--danger-ring` | `#F6D5D2` | ring around the record button |
| `--role-health-bg` / `--role-health-ink` | `#E6EAF5` / `#2B3F7A` | doctor, nurse, institution badges |
| `--role-family-bg` / `--role-family-ink` | `#F3E8F2` / `#6B2A63` | family badge |
| `--player` / `--player-mark` | `#16201C` / `#F2B66B` | audio player bar, cited fragment |

Radii: card 18px, list card inside card 14px, field 12px, primary button 26px (pill), chip 999px.
Spacing: page gutter 16px; gap between sections 16px; card padding 16px; row padding 14px 16px.

## Type

- Display: **Bricolage Grotesque** 600/700. Brand 22–24px, screen title 26–30px, section title 18px.
- Body: **Atkinson Hyperlegible** 400/700, 16px, line-height 1.4. Captions 13–14px. Section labels 13–14px, uppercase, letter-spacing 0.04em, `--muted`.
- Patient view only: body 19px, buttons ≥64px tall.
- Load both with `next/font/google`. No other fonts.

## Components

**Use shadcn/ui only.** Do not write custom components or plain HTML when a shadcn component exists; compose shadcn primitives instead. If something custom is truly necessary, say why in the PR. Add components with `npx shadcn@latest add <name>` (from `web/`). Icons: `lucide-react`.

The tokens above are wired as the shadcn theme in `web/app/globals.css` (`--primary`, `--destructive`, `--border`, … plus `warning`, `danger`, `danger-soft`, `success-soft`, `role-health`, `role-family`). CercanIA variants live inside the shadcn files:

| Design element | shadcn component | Variant / usage |
|---|---|---|
| Primary action (52px pill) | `Button` | `size="xl"` |
| Secondary action | `Button` | `variant="outline-primary"` |
| "Necesito ayuda", record | `Button` | `variant="danger"` |
| Icon button, back | `Button` | `size="icon-touch"` (44px) |
| Chips: alert / red flag / not mentioned / ok / roles | `Badge` | `warning`, `danger`, `missing`, `success`, `health`, `family`, `neutral` |
| Red flag banner | `Alert` | `variant="danger"` (alerts), `"danger-soft"` (family) |
| "Not for emergencies" notice | `Alert` | `variant="warning"` |
| Cards | `Card` + `CardHeader` / `CardContent` | |
| Lists and rows (reports, items, patients, citations) | `Item`, `ItemGroup`, `ItemSeparator` | |
| Progress of checklist | `Progress` | |
| Patient avatar | `Avatar` + `AvatarFallback` | |
| Forms | `Field`, `FieldLabel`, `FieldDescription`, `Input`, `Select` | |
| Search and chat composer | `InputGroup` | |
| 6-digit code | `InputOTP` | |
| Sign-up / login switch | `Tabs` | |
| Help confirmation | `AlertDialog` | |
| Chat (Ask, Messages) | `Bubble`, `Message` | |
| Empty / error states | `Empty` | |
| Loading | `Skeleton`, `Spinner` | |
| Toasts | `Sonner` | |

App chrome shared by all screens (centered 480px column, top bar, bottom nav, bottom action bar) is the only custom composition: `web/components/app/shell.tsx`, built from `Button` and `Badge`.

## Accessibility rules

- Touch targets ≥44px (patient view ≥64px).
- Real `<button>`, `<a href>`, `<input>` with `<label>`; `aria-label` on icon-only buttons; decorative SVG `aria-hidden`.
- Never color alone: alerts also carry an icon or text; verified uses ✓ plus the word.
- Red flags and help responses use `role="alert"`.

## Screens → routes → tickets → endpoints

| Artboard | Route | Ticket | Data |
|---|---|---|---|
| `SignIn` | `/login` | CIA-32 | `POST /auth/signup`, `/auth/login` |
| `Code` (+ `Link` as the expired state) | `/login/code` | CIA-32 | `POST /auth/verify` |
| `Patients` | `/patients` | CIA-33 | `GET /me/patients` |
| `AddPatient` | `/patients/new` | CIA-34 | `POST /patients`, members, invites |
| `Main` | `/patients/[id]` | CIA-11 | `GET /patients/{id}`, `/reports` |
| `Report` | `/patients/[id]/reports/[reportId]` | CIA-11 | `GET /patients/{id}/reports` |
| `NewReport` | `/patients/[id]/reports/new` | CIA-31 | `POST /patients/{id}/reports` |
| `Alerts` | `/patients/[id]/alerts` | CIA-12 | reports' `alerts`, `red_flag` |
| `Ask` | `/patients/[id]/ask` | CIA-13 | `POST /patients/{id}/query` |
| `Family` | `/patients/[id]/family` | CIA-12 | same data, read-only |
| `Messages` | `/patients/[id]/messages` | CIA-36 (bonus) | `/patients/{id}/messages` |
| `Patient` | `/patients/[id]/me` | CIA-35 | `/patients/{id}/patient-messages` |

**`NewReport` result state (CIA-46).** Built from the structured `ProcessResult`, not from `confirmation_text` (which is shown only inside the emergency banner). Top to bottom: emergency banner (`red_flag`) or "Reporte registrado" card; warning if triage failed; for voice reports a "Escuchar tu nota" player that plays the local recording (a `blob:` URL, since the stored audio may not be ready yet), for typed reports the typed text; "Lo que registramos": one row per mentioned item (same row as the `Report` screen) with label, value, level badge, medication dose badges, the verbatim quote (a play button seeking to its fragment when the item has audio times) and its verification (verificada, or "Esta cita no aparece en la transcripción"); "No mencionaste" chips; alerts; "Ver reporte" and "Mandar otra nota".

All screens read data through `web/lib/api.ts`. Until the backend is ready it returns fake data shaped exactly like `docs/contract.md` (`NEXT_PUBLIC_USE_FAKE_DATA=1`); that is declared in README "Simulated".
