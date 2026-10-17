# Contract

Source of truth for integration between backend, web and input layers. Change it only in the same commit as the code that changes. The web owner builds against fake data shaped exactly like this and must not wait for the backend.

## Checklist items (fixed enum)

`appetite`, `sleep`, `urination`, `medication`, `mood`, `mobility`, `pain`, `incidents`

Edit this list only after validating with a caregiver contact. Update `AGENTS.md` section 4 as well.

## Core function

```
process_report(patient_id, sender_id, transcript, audio_ref, message_id) -> ProcessResult
```

`sender_id` is a caregiver for shift reports; any registered role can trigger an emergency report (`report.kind = "emergency"`, no checklist items).

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
      "item": "appetite",
      "detail": "Appetite low for 3 consecutive shifts.",
      "report_refs": ["rep_121", "rep_122", "rep_123"]
    }
  ],
  "red_flag": false,
  "triage": {
    "status": "ok",
    "emergency": false,
    "reason": null,
    "quote": null,
    "quote_verified": null
  },
  "confirmation_text": "I recorded: ate little at dinner. Did not mention the 08:00 medication. How did she sleep?"
}
```

Rules:
- `quote` must be a substring (after normalization: case, accents, punctuation, whitespace; whole words only) of `transcript`. If not, set `quote_verified: false` and do not use the value for alerts.
- `medication` items carry `details.doses`: `[{ "plan_ref": "med_002", "time": "08:00", "given": true | false | null, "quote": "…", "quote_verified": true }]`. Only medications and times in the active care plan are accepted; `given: null` means unclear.
- Items not mentioned: `value: null`, `quote: null`. Never infer.
- `level` is a coarse category used by code to compare over time (e.g. appetite `normal` / `low` / `none`). Optional for display.
- `red_flag` is decided by the **model** in the triage step (`triage.py`), not by a phrase list. `red_flag == triage.emergency`. The reply text sent on an emergency is fixed in code.
- `triage.quote` is verified like any other quote, but `quote_verified: false` **never** turns an emergency off; it is only shown as unverified.
- `triage.status` is `ok` or `failed` (model error/timeout). On `failed`, `red_flag` is `false`, the report is still stored and the reply still includes the fixed emergency line.
- On an emergency, `confirmation_text` is the fixed emergency message and asks no checklist questions.

## Alert types

| type | produced by | meaning |
|---|---|---|
| `omission` | compare.py vs care plan | scheduled medication/indication not mentioned or time mismatch |
| `change` | compare.py vs history | deviation from the patient's usual pattern |
| `missing_item` | compare.py vs checklist | checklist item not covered in this report |
| `emergency` | triage.py (model) | the message describes an emergency; carries `reason`, `evidence_quote`, its verification status and `notifications: [{ "to": "health_provider" \| "caregiver" \| "family", "person_id": "…" \| null, "status": "sent" \| "failed", "error": null }]` |

## Endpoints

All responses are JSON. Errors: `{ "error": { "code": "string", "message": "human-readable" } }`.

### `GET /patients/{patient_id}`

```json
{
  "id": "pat_001",
  "display_name": "Rosa (fictional)",
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
      "kind": "shift",
      "sender": { "id": "cg_001", "display_name": "Ana (fictional)", "role": "caregiver" },
      "transcript": "…",
      "audio_url": "/media/rep_123.ogg",
      "items": [],
      "missing_items": [],
      "alerts": [],
      "red_flag": false,
      "triage": { "status": "ok", "emergency": false, "reason": null, "quote": null, "quote_verified": null }
    }
  ],
  "next_before": null
}
```

`kind` is `shift` (caregiver report, has items) or `emergency` (raised by another role, `items` is empty). `sender.role` is the sender's role for this patient. `triage` is `null` for seed fixtures, which never went through triage.

### `GET /reports/{report_id}/versions`

Returns all versions, oldest first. Previous versions are immutable.

### `POST /reports/{report_id}/corrections`

```json
{ "corrections": [ { "item": "appetite", "value": "ate normally" } ], "by": "cg_001" }
```

Creates a new version. Does not modify the old one.

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

### `GET /webhook/whatsapp`

Meta Cloud API verification handshake. Query `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`. Returns the challenge as plain text when the token matches `WHATSAPP_VERIFY_TOKEN`, else 403 `verification_failed`.

### `POST /webhook/whatsapp`

Meta Cloud API webhook (JSON). Requests without a valid `X-Hub-Signature-256` (HMAC-SHA256 of the body with `WHATSAPP_APP_SECRET`) get 403 `invalid_signature`. Response on success: `{ "status": "received" }`. Status updates (delivered/read) are acked and ignored. Voice notes are transcribed; text messages are treated as a typed report; other types get a reply asking for a voice note.

Acknowledge immediately (HTTP 200), then process asynchronously. Dedupe by provider message id. Identify the sender by phone number and route by role (AGENTS.md §4.1). If the sender has several patients, ask "which patient?" before processing. Target, not built yet (CIA-7): every registered sender's message goes through triage, including family, doctor and patient, and the emergency reply goes out before the patient question and before extraction. Today the bot behaves as listed below.

Bot behavior (all replies are WhatsApp text):
- Sender phone not in `person.phone` → "number not registered" message, which always includes the fixed emergency line; nothing processed, no model call.
- No patient where the sender has `send_report` → "no patients assigned" message. Today this is where family, doctor and patient messages stop; they do not reach triage yet (see target above).
- Several patients → numbered "¿De qué paciente es el reporte?" question; the report is kept (in memory, 30 min) and processed once the caregiver answers with the number or part of the name. `message_id` is the report's id, not the answer's.
- Reports sent while a choice is pending (voice, or typed text of 4+ words) are queued, never dropped: the bot says it kept them and asks about each in arrival order. Reports that expire without a choice are announced on the caregiver's next message so they can resend them.
- After `process_report`: `confirmation_text` (or the result's `message` for `needs_retry` / `unclear`). When `red_flag` is true, a fixed line written in code is prepended: "⚠️ Si es una emergencia, llamá a emergencias o al médico ahora."
- `process_report` not deployed → the caregiver is told nothing was stored.

## Reports from the web app

### `POST /patients/{patient_id}/reports`

Same report a caregiver can send by WhatsApp. Either JSON text or multipart audio:

```json
{ "client_id": "web_7f3c", "text": "Casi no comió nada en la cena…" }
```

Multipart: `client_id` + `audio` file (webm/ogg/m4a). Audio goes through the same transcription step. Returns `ProcessResult` exactly as `process_report`. Idempotent on `client_id`: the `message_id` passed to `process_report` is `web:<person_id>:<client_id>`, so one user's id can never match another user's report or a WhatsApp message.

Requires the `send_report` permission for that patient (`ROLE_PERMISSIONS` in `backend/app/models.py`; today only `caregiver`). Errors, all as `{ "error": { "code", "message" } }` with a message the UI can show as is:

| HTTP | `code` | When |
|---|---|---|
| 400 | `client_id_missing`, `text_missing`, `audio_missing`, `audio_empty`, `invalid_json` | Bad input |
| 401 | `unauthenticated` | No caller identity |
| 403 | `forbidden` | Role lacks `send_report` for this patient |
| 404 | `not_found` | Unknown patient |
| 409 | `client_id_conflict` | Same `client_id` already used by this user for another patient |
| 413 | `audio_too_large` | Audio over 4 MB (Vercel caps request bodies at 4.5 MB) |
| 415 | `unsupported_audio`, `unsupported_media_type` | Not webm/ogg/m4a/mp3/wav, or neither JSON nor multipart |
| 502 | `transcription_failed` | Transcription failed; ask to retry or type |
| 503 | `processing_unavailable` | `process_report` not deployed yet; nothing was stored |

A repeated `client_id` is not transcribed again; the stored report's result is returned.

### Magic link

`POST /auth/link` is triggered when a user messages the bot. The bot replies with a single-use URL that expires after `MAGIC_LINK_TTL_MINUTES`. Roles: `caregiver`, `family` (read-only), `doctor` (only role that edits the care plan), `patient` (own profile and care plan; no reports or alerts). A role is per patient. Endpoints return `403` with an error `code: "forbidden"` when the role lacks the permission.

## Seed data

`backend/app/seed.py` creates 2-3 fictional patients, each with a care plan, one caregiver, one family member, and a few days of history so that `change` alerts can be demonstrated. No real names or data.
