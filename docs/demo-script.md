# Live demo script

For whoever runs the live demo. There is no backup video (team decision, Oct 18), so the fallbacks below are the safety net. It follows AGENTS.md §15: a report goes in, the record and an omission alert come out, then a question gets an answer cited from the voice note. **3 minutes.** Everything shown is fictional seed data.

## Before the demo

- **Wake both services** a minute before: open https://cercania-api.onrender.com/health and https://cercania-web.onrender.com. The free plan sleeps after ~15 min; the first request takes about a minute.
- **Log in** at https://cercania-web.onrender.com/login with a team phone that is linked to the caregiver Ana (`cg_001`) and verified in the Twilio trial (see CIA-42). The seed phones are fictional and cannot receive the SMS code.
- **Rosa's history must be clean:** only the 3 seed reports (Oct 15–17). Every rehearsal adds a real report, and the next "change" alert counts it ("4 turnos seguidos" instead of "3"). After rehearsing, ask Dev C to delete the rehearsal reports.
- Show it from a phone (screen mirrored) or a desktop browser narrowed to about 480 px.
- **Have the note copied to the clipboard** on the demo device, ready for "Escribir" if the microphone or the venue noise fails.
- Have a second device already logged in as Ana, in case the first one loses its session or connection (the session lasts 30 days on each device).

## The demo

| Time | On screen | What happens / what to say |
|---|---|---|
| 0:00–0:20 | Mis pacientes | "When the shift changes, what the caregiver saw gets lost. CercanIA records it from a voice note." |
| 0:20–1:10 | Rosa → **Nuevo reporte** → record | Dictate the note below and send it. The confirmation appears in a few seconds. |
| 1:10–1:35 | The confirmation | Point at: what was recorded, **omissions** (Enalapril 08:00, Metformina 08:00 not mentioned), the **change** (appetite low, 3 shifts in a row) and the **missing item** (sleep). "The model only reads; code compares against the care plan and the history." |
| 1:35–2:00 | Open the new report | Every item shows the caregiver's exact words and "verificada". **Tap the quote "Comió poco en la cena"**: it plays exactly that fragment of the voice note. |
| 2:00–2:40 | **Preguntar** → "¿Cómo viene comiendo?" | The answer cites the reports. **Tap the citation from today's report**: it plays the exact words. Seed reports were entered as text, so their citations have no audio. |
| 2:40–3:00 | Back to Rosa | Close with the limits: no diagnosis and no doses, fictional data, and the simulated parts (SMS code on the Twilio trial; notifications only reach people through the web inbox). |

**Note to dictate** (tested through the real pipeline: status `ok` in 2.7 s, with exactly the alerts above):

> Terminé el turno con Rosa. Comió poco en la cena, dejó la mitad del plato. Le di el enalapril de las ocho de la noche. Orinó normal. Estuvo tranquila y caminó con el andador por el pasillo. No tuvo dolor y no hubo caídas.

## If something goes wrong

- **The microphone fails or there is noise:** use "Escribir" on the same screen and paste the note. It goes through the same pipeline.
- **"El servicio de IA no respondió a tiempo":** that is Groq's free-tier limit (8,000 tokens/minute). Wait 30 seconds and send again; nothing was stored.
- **Every screen sends you back to login:** see the troubleshooting section in `docs/deploy.md`.

## Be ready to answer

- **"Why is the 08:00 dose flagged on an evening shift?"** The comparison checks every time in the care plan; it does not know shift hours yet. It flags what was not mentioned, never what was given.
- **"How do you know the AI is right?"** Every value carries a verbatim quote that code checks against the transcript. On 20 fictional eval cases (6 never used for tuning): fields 98%, omissions 100%, emergencies 4/4 with no false alarms (`eval/RESULTS.md`).

## Optional extra (if there is time)

The patient view: log in as a patient and tap "Necesito ayuda". The team's inbox gets the alert immediately, with no model involved. It needs a phone linked to the patient Jorge (`ptl_002`).
