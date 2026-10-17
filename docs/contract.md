# Contract

Source of truth for integration between backend, web and input layers. Change it only in the same commit as the code that changes. The web owner builds against fake data shaped exactly like this and must not wait for the backend.

## Checklist items (fixed enum)

`appetite`, `sleep`, `urination`, `medication`, `mood`, `mobility`, `pain`, `incidents`

Edit this list only after validating with a caregiver contact. Update `AGENTS.md` section 4 as well.

## Core function

```
process_report(patient_id, caregiver_id, transcript, audio_ref, message_id) -> ProcessResult
```

- Idempotent on `message_id`: a repeated delivery returns the existing result and creates nothing.
- Never raises to the caller for model errors; returns `status: "needs_retry"` or `status: "unclear"` with a message the bot can send.

```json
{
  "status": "ok",
  "report": { "id": "rep_123", "version": 1 },
  "items": [
    {
      "item": "appetite",
      "value": "ate little at dinner",
      "level": "low",
      "quote": "casi no comio nada en la cena",
      "quote_verified": true
    },
    {
      "item": "sleep",
      "value": null,
      "level": null,
      "quote": null,
      "quote_verified": null
    }
  ],
  "missing_items": ["sleep", "urination"],
  "alerts": [
    {
      "type": "omission",
      "detail": "Care plan says 08:00 medication; report does not mention it.",
      "plan_ref": "med_002",
      "evidence_quote": null
    },
    {
      "type": "change",
      "detail": "Appetite low for 3 consecutive shifts.",
      "report_refs": ["rep_121", "rep_122", "rep_123"]
    }
  ],
  "red_flag": false,
  "confirmation_text": "I recorded: ate little at dinner. Did not mention the 08:00 medication. How did she sleep?"
}
```

Rules:
- `quote` must be a substring (after normalization: case, accents, whitespace) of `transcript`. If not, set `quote_verified: false` and do not use the value for alerts.
- Items not mentioned: `value: null`, `quote: null`. Never infer.
- `level` is a coarse category used by code to compare over time (e.g. appetite `normal` / `low` / `none`). Optional for display.
- `red_flag: true` is set by a fixed-rule phrase list (code), not by the model.

## Alert types

| type | produced by | meaning |
|---|---|---|
| `omission` | compare.py vs care plan | scheduled medication/indication not mentioned or time mismatch |
| `change` | compare.py vs history | deviation from the patient's usual pattern |
| `missing_item` | compare.py vs checklist | checklist item not covered in this report |

## Endpoints

All responses are JSON. Errors: `{ "error": { "code": "string", "message": "human-readable" } }`.

### `GET /patients/{patient_id}`

```json
{
  "id": "pat_001",
  "display_name": "Rosa (fictional)",
  "location": "Room 12",
  "care_plan": {
    "medications": [
      { "id": "med_002", "name": "Example-med", "dose": "as prescribed", "times": ["08:00", "20:00"] }
    ],
    "indications": ["Encourage fluids", "Assist when walking"],
    "allergies": []
  }
}
```

### `GET /patients/{patient_id}/reports`

Query: `?limit=20&before=<iso>`

```json
{
  "reports": [
    {
      "id": "rep_123",
      "version": 1,
      "created_at": "2026-10-17T21:05:00-03:00",
      "caregiver": { "id": "usr_001", "display_name": "Ana (fictional)" },
      "transcript": "…",
      "audio_url": "/media/rep_123.ogg",
      "items": [],
      "missing_items": [],
      "alerts": []
    }
  ],
  "next_before": null
}
```

### `GET /reports/{report_id}/versions`

Returns all versions, oldest first. Previous versions are immutable.

### `POST /reports/{report_id}/corrections`

```json
{ "corrections": [ { "item": "appetite", "value": "ate normally" } ] }
```

Creates a new version. Does not modify the old one. The author of the new version is the session user, never a field in the body. Only `caregiver` memberships can correct.

### `POST /patients/{patient_id}/query`

```json
{ "question": "Did she take the evening medication yesterday?" }
```

```json
{
  "answer": "The report from yesterday 21:05 does not mention the 20:00 medication.",
  "citations": [
    { "report_id": "rep_122", "quote": "…", "audio_start_sec": 12.4, "audio_end_sec": 15.0 }
  ],
  "confidence": "answered",
  "note": null
}
```

`confidence` is `answered` or `unclear`. If the records do not contain the answer, return `unclear` and say so; never guess. Every citation quote must verify against the cited transcript.

### `POST /webhook/whatsapp`

Acknowledge immediately (HTTP 200), then process asynchronously. Dedupe by provider message id. Identify the caregiver by sender phone number. If the caregiver has several patients, ask "which patient?" before processing.

Before anything else (including the ack), verify the provider signature on the raw request (`X-Twilio-Signature` for Twilio, `X-Hub-Signature-256` for Meta Cloud API) with `WHATSAPP_AUTH_TOKEN` from the environment, and check that the destination number is `WHATSAPP_FROM_NUMBER`. If either check fails, return `403` and process nothing. The sender phone is trusted only after this check.

## Roles (fixed enum)

`caregiver`, `family`, `patient`, `doctor`, `nurse`, `institution`. `doctor`, `nurse` and `institution` share the "health team" permissions in `AGENTS.md` section 6. A role belongs to a membership (user + patient), not to the user. Only `doctor` edits the care plan after creation (each edit is a new plan version); `patient` never sees reports or alerts. Endpoints return `403` with error `code: "forbidden"` when the role lacks the permission (`ROLE_PERMISSIONS` in `backend/app/models.py`).

## Auth (6-digit code by WhatsApp)

No passwords. The web app keeps the session in a cookie set by `POST /auth/verify` with `HttpOnly`, `Secure` and `SameSite=Lax`; every endpoint below except `/auth/*` and `/webhook/*` requires it and returns `401 { "error": { "code": "unauthenticated" } }` without it.

### `POST /auth/signup`

```json
{ "name": "Ana Pérez (fictional)", "email": "ana@example.com", "phone": "+59899000000" }
```

### `POST /auth/login`

```json
{ "phone": "+59899000000" }
```

Both send a 6-digit code to the WhatsApp number and reply:

```json
{ "status": "code_sent", "phone_last4": "0000", "expires_in_sec": 600, "resend_after_sec": 60 }
```

Errors: `phone_invalid`, `too_many_requests`, `whatsapp_unreachable` (message tells the user to message the bot first).

Anti-enumeration: these two endpoints must not reveal whether a phone or email is registered. `POST /auth/login` returns the same `code_sent` body for an unknown phone and sends nothing. `POST /auth/signup` for a phone that already has an account sends a normal login code instead of creating a second user. A conflicting email is reported only after the code is verified (`email_taken` from `POST /auth/verify`).

### `POST /auth/verify`

```json
{ "phone": "+59899000000", "code": "470123" }
```

```json
{ "user": { "id": "usr_001", "name": "Ana Pérez (fictional)" }, "memberships": [ { "patient_id": "pat_001", "role": "caregiver" } ] }
```

Codes are single-use, expire after `LOGIN_CODE_TTL_MINUTES` (default 10), are stored hashed, and lock after 5 wrong attempts. Errors: `code_invalid`, `code_expired`, `too_many_attempts`, `email_taken` (signup only: the email belongs to another account; the user is asked for a different one). Pending invites for that phone/email become memberships here.

### `POST /auth/logout`

Clears the session.

## Patients and team

### `GET /me/patients`

Patients the current user has a membership for, with what the list screen needs:

```json
{
  "patients": [
    {
      "id": "pat_001",
      "display_name": "Rosa (fictional)",
      "location": "Room 12",
      "role": "caregiver",
      "last_report_at": "2026-10-17T21:05:00-03:00",
      "open_alerts": 2,
      "red_flag": true,
      "missing_report": false
    }
  ]
}
```

`missing_report` is computed by code (no report in the current shift window), never by the model.

### `POST /patients`

```json
{
  "display_name": "Rosa (fictional)",
  "location": "Room 12",
  "care_plan": {
    "medications": [ { "name": "Example-med", "dose": "as prescribed", "times": ["08:00", "20:00"] } ],
    "indications": ["Encourage fluids"],
    "allergies": []
  }
}
```

Returns the patient as in `GET /patients/{patient_id}`. The creator becomes `caregiver` and sets the initial care plan; after that only a `doctor` can edit it. Doses are stored as entered; nothing is computed.

### `GET /patients/{patient_id}/members`

```json
{ "members": [ { "user_id": "usr_001", "name": "Ana Pérez (fictional)", "role": "caregiver" } ], "invites": [ { "id": "inv_001", "contact": "+59899111111", "role": "family", "status": "pending" } ] }
```

### `POST /patients/{patient_id}/invites`

```json
{ "contact": "+59899111111", "role": "family" }
```

`contact` is a WhatsApp number or an email. Sends a WhatsApp/email invite; the membership is created when that person verifies a code (`POST /auth/verify`). Only `caregiver` memberships can invite (`403 forbidden` otherwise), matching `AGENTS.md` section 6. Health-team and family members cannot invite.

## Reports from the web app

### `POST /patients/{patient_id}/reports`

Same report a caregiver can send by WhatsApp. Either JSON text or multipart audio:

```json
{ "client_id": "web_7f3c", "text": "Casi no comió nada en la cena…" }
```

Multipart: `client_id` + `audio` file (webm/ogg/m4a). Audio goes through the same transcription step. Returns `ProcessResult` exactly as `process_report`. Idempotent on `client_id` (used as the `message_id`).

## Patient messages

### `POST /patients/{patient_id}/patient-messages`

Only for the `patient` role (and caregivers testing).

```json
{ "kind": "feeling", "text": "me duele un poco la rodilla" }
```

```json
{ "kind": "help" }
```

`kind` is `feeling` or `help`. `feeling` accepts `text` or multipart `audio`. Response:

```json
{ "id": "pm_001", "kind": "help", "notified": ["usr_001", "usr_004"], "red_flag": false, "message_for_patient": "Ya avisamos a tu equipo. Si es una emergencia, llamá a emergencias." }
```

`help` is a fixed rule: notify every caregiver and health-team member by WhatsApp immediately; the model is never involved.

`feeling` is checked against the red-flag phrase list in code: the `text` field, or for `audio` the transcript, before replying. Audio must never skip this check; if transcription fails, return `transcription_failed` and the UI asks the patient to retry or type, always showing "si es una emergencia, llamá a emergencias". When `red_flag` is `true`, the team is notified as for `help` and `message_for_patient` is this fixed, code-generated text (never written by the model):

```json
{ "id": "pm_002", "kind": "feeling", "notified": ["usr_001", "usr_004"], "red_flag": true, "message_for_patient": "Avisamos a tu equipo. Si es una emergencia, llamá a emergencias o a tu médico ahora." }
```

### `GET /patients/{patient_id}/patient-messages`

Latest first: `{ "messages": [ { "id", "kind", "text", "created_at", "seen_by": [ { "user_id", "name" } ] } ] }`.

## Family <-> health team messages (bonus)

### `GET /patients/{patient_id}/messages`

```json
{ "messages": [ { "id": "msg_001", "from": { "user_id": "usr_005", "name": "Marta (fictional)", "role": "family" }, "text": "…", "created_at": "2026-10-17T15:02:00-03:00", "read": true } ] }
```

### `POST /patients/{patient_id}/messages`

```json
{ "text": "Hola doctora…" }
```

Only `family` and health-team roles. Human-to-human: no model call. The UI always shows "not for emergencies".

## Seed data

`backend/app/seed.py` creates 2-3 fictional patients, each with a care plan, and fictional users for every role (one caregiver, one doctor, one nurse, one family member, the patient), plus a few days of history so that `change` alerts can be demonstrated. No real names or data.
