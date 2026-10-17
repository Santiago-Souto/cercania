# WhatsApp setup (Meta Cloud API)

The bot uses Meta's WhatsApp Cloud API directly, with the free test number. Steps 1-4 happen in Meta's dashboard (they need a person logged in). Step 5 is automated by `backend/scripts/setup_whatsapp.py`.

Menu names in Meta's dashboard change from time to time; if one below does not match, look for the closest equivalent.

## 1. Create the app

1. Go to <https://developers.facebook.com/apps> and log in (create a developer account if asked).
2. **Create app** -> use case **Other** -> type **Business** -> name it `CercanIA`.
3. In the app dashboard, add the **WhatsApp** product and click **Set up**. Meta creates a test business account and a test sender number.

## 2. Copy the ids and secrets into `.env`

From **WhatsApp -> API Setup**:

| `.env` variable | Where to find it |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | "Phone number ID" under the test number |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | "WhatsApp Business Account ID" |
| `WHATSAPP_TOKEN` | "Temporary access token" (expires in ~24 h, see step 4) |

From **App settings -> Basic**:

| `.env` variable | Where to find it |
|---|---|
| `WHATSAPP_APP_ID` | "App ID" |
| `WHATSAPP_APP_SECRET` | "App secret" -> Show |

Make up a random string for `WHATSAPP_VERIFY_TOKEN` (e.g. `openssl rand -hex 16`).

## 3. Add the phones that will talk to the bot

The test number only talks to numbers you add. In **WhatsApp -> API Setup -> To**, click **Manage phone number list** and add each team phone (and the demo phones). Each one gets a code by WhatsApp to confirm.

## 4. Permanent token (do this before the demo)

The temporary token stops working after ~24 h. To get one that does not expire:

1. <https://business.facebook.com/settings> -> **Users -> System users** -> **Add** (role Admin).
2. **Add assets** -> your app -> full control. Also add the WhatsApp account.
3. **Generate new token** -> select the app -> permissions `whatsapp_business_messaging` and `whatsapp_business_management` -> expiry **Never**.
4. Replace `WHATSAPP_TOKEN` in `.env` and in Render.

## 5. Connect the webhook (automated)

1. Put all the variables above, plus `GROQ_API_KEY`, in **Render -> cercania-api -> Environment** and wait for the redeploy. Set `PUBLIC_BASE_URL` to the Render URL (e.g. `https://cercania-api.onrender.com`).
2. Locally, with the same values in `.env`:

   ```bash
   cd backend
   python scripts/setup_whatsapp.py --test-to 5491122334455   # your number, digits only
   ```

   The script checks the server is up, checks the verify token matches, registers the webhook URL with Meta, subscribes the app to the business account, and sends you the `hello_world` test message. It stops with a clear reason at the first step that fails.
3. Reply to the test message with a voice note. The server logs show `Transcript ready for message ...` (the text itself is never logged).

To test without deploying, run the API locally and expose it with a tunnel (`ngrok http 8000`), then use the tunnel URL as `PUBLIC_BASE_URL`.

## Troubleshooting

- **Error 131030 "Recipient phone number not in allowed list"**: add the number in step 3. Argentine numbers arrive as `549...`; the bot retries without the `9` automatically.
- **Error 190 / "Session has expired"**: the temporary token expired. Generate a new one or do step 4.
- **No webhook calls arrive**: check the app is subscribed (rerun the script) and that `WHATSAPP_APP_SECRET` on Render matches; requests with a bad signature are rejected with 403 and logged.
- **Render free plan sleeps** after inactivity; the first request can take ~1 min. Open `/health` before a demo.
