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
      "caregiver": { "id": "cg_001", "display_name": "Ana (fictional)" },
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

### `POST /webhook/whatsapp`

Acknowledge immediately (HTTP 200), then process asynchronously. Dedupe by provider message id. Identify the caregiver by sender phone number. If the caregiver has several patients, ask "which patient?" before processing.

### Magic link

`POST /auth/link` is triggered when a user messages the bot. The bot replies with a single-use URL that expires after `MAGIC_LINK_TTL_MINUTES`. Roles: `caregiver`, `family` (read-only).

## Seed data

`backend/app/seed.py` creates 2-3 fictional patients, each with a care plan, one caregiver, one family member, and a few days of history so that `change` alerts can be demonstrated. No real names or data.
