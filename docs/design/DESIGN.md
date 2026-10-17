# CercanIA design

Source of truth for the web app's look and screens. Build every screen from this file and the artboards in `screens/`. If the UI needs to change, change the design first (or in the same PR), then the code.

- Live canvas: "CercanIA mobile screens" (Claude artifact, ask Dev B for access). The files in `screens/` are snapshots of it: open them as reference, never import them into the app.
- Mobile-first: designed at 390×844. On desktop the app is the same layout in a centered column, max 480px wide.
- UI copy in Spanish (Río de la Plata: "vos", "contá", "acordate"). All names and data shown are fictional.

## Tokens

Defined once as CSS variables in `web/app/globals.css`. Never hardcode a hex in a component.

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

| Component | What it is | Seen in |
|---|---|---|
| `AppShell` | centered 480px column, ground background, optional header and bottom nav | all |
| `BottomNav` | 3 tabs: Inicio, Alertas, Preguntar; active tab in `--primary` and bold | Main, Alerts, Ask |
| `TopBar` | 44px round back button + title + subtitle | Report, NewReport, AddPatient, Code, Messages |
| `Card` | surface, 1px `--line`, radius 18 | all |
| `Chip` | variants: `alert` (warn), `redflag` (danger, white text), `missing` (dashed), `ok` (primary-soft), `role-*` | Main, Patients, Report, Alerts |
| `Button` | `primary` (52px pill), `secondary` (outlined), `danger`; always a real `<button>` or `<a>` | all |
| `ReportItem` | label (caps), value, verbatim quote in italics, status: verified / unverified (warn tint + explanation) / not mentioned (dashed chip) | Report |
| `AlertCard` | grouped by type: omission, change, missing_item; links to the report | Alerts |
| `RedFlagBanner` | `role="alert"`, danger background, quote + the fixed text "Contactá a emergencias o al médico." | Alerts, Family (soft variant) |
| `CitationButton` | play icon + quote + "report time · caregiver · start–end" | Ask |
| `AudioBar` | dark player bar with the cited fragment marked | Ask, Report |
| `RecordButton` | 112px round, red while recording, timer below | NewReport, Patient |
| `CodeInput` | 6 numeric boxes, auto-advance, paste, `autocomplete="one-time-code"` | Code |
| `Field` | `<label>` + input/select, 48px tall, error text below | SignIn, AddPatient |

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

All screens read data through `web/lib/api.ts`. Until the backend is ready it returns fake data shaped exactly like `docs/contract.md` (`NEXT_PUBLIC_USE_FAKE_DATA=1`); that is declared in README "Simulated".
