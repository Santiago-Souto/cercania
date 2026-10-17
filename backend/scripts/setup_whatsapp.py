"""Connects a Meta WhatsApp Cloud API app to our deployed webhook.

Run from backend/ after the manual steps in docs/whatsapp-setup.md:

    python scripts/setup_whatsapp.py                     # check + register webhook
    python scripts/setup_whatsapp.py --test-to 54911...  # also send a test message

Reads the variables from the environment or from the repo's .env file.
Every step prints OK or a clear reason it failed; nothing is changed in Meta
until our own server passes its checks.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.whatsapp import graph_url  # noqa: E402

REQUIRED = [
    "PUBLIC_BASE_URL",
    "WHATSAPP_APP_ID",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "WHATSAPP_VERIFY_TOKEN",
]


def load_dotenv() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-to", help="Phone number (digits, with country code) to send the hello_world template to")
    args = parser.parse_args()

    load_dotenv()
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    step("Environment variables", not missing, "missing " + ", ".join(missing) if missing else "")

    base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    callback = f"{base}/webhook/whatsapp"
    verify_token = os.environ["WHATSAPP_VERIFY_TOKEN"]
    token = os.environ["WHATSAPP_TOKEN"]

    with httpx.Client(timeout=60) as http:
        # 1-2: our server must be up and answer the handshake before Meta tries it.
        try:
            health = http.get(f"{base}/health")
            step("Server health", health.status_code == 200, f"{base}/health -> {health.status_code}")
        except httpx.HTTPError as exc:
            step("Server health", False, f"{base}/health unreachable ({exc}). Is the deploy up? (Render free sleeps; retry)")

        handshake = http.get(
            callback,
            params={"hub.mode": "subscribe", "hub.verify_token": verify_token, "hub.challenge": "cercania-check"},
        )
        step(
            "Webhook handshake",
            handshake.text == "cercania-check",
            "" if handshake.text == "cercania-check" else
            f"got {handshake.status_code}. WHATSAPP_VERIFY_TOKEN on the server differs from the local one",
        )

        # 3: register the callback for the app. Meta calls our GET handshake now.
        app_id = os.environ["WHATSAPP_APP_ID"]
        app_token = f"{app_id}|{os.environ['WHATSAPP_APP_SECRET']}"
        sub = http.post(
            graph_url(f"{app_id}/subscriptions"),
            data={
                "object": "whatsapp_business_account",
                "callback_url": callback,
                "verify_token": verify_token,
                "fields": "messages",
                "access_token": app_token,
            },
        )
        step("Register webhook with Meta", sub.status_code == 200, sub.text[:300] if sub.status_code != 200 else callback)

        # 4: deliver this business account's messages to the app.
        waba = os.environ["WHATSAPP_BUSINESS_ACCOUNT_ID"]
        subscribed = http.post(graph_url(f"{waba}/subscribed_apps"), headers={"Authorization": f"Bearer {token}"})
        step(
            "Subscribe app to WhatsApp Business Account",
            subscribed.status_code == 200,
            subscribed.text[:300] if subscribed.status_code != 200 else "",
        )

        # 5 (optional): templates can be sent outside the 24h window, so this
        # works even before the recipient has written to the bot.
        if args.test_to:
            sent = http.post(
                graph_url(f"{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"),
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": args.test_to,
                    "type": "template",
                    "template": {"name": "hello_world", "language": {"code": "en_US"}},
                },
            )
            step(
                f"Send test message to {args.test_to}",
                sent.status_code == 200,
                sent.text[:300] if sent.status_code != 200 else "check the phone, then reply with a voice note",
            )

    print("\nDone. Send a voice note to the test number and watch the server logs for 'Transcript for message'.")


if __name__ == "__main__":
    main()
