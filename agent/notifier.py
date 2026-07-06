"""Send notifications by Email (Gmail SMTP) and Telegram (Bot API)."""
import smtplib
import time
from email.mime.text import MIMEText

import requests

EMAIL_ATTEMPTS = 3
EMAIL_RETRY_DELAY_SECONDS = 5


def send_email(subject, body, to_address, gmail_address, gmail_app_password):
    if not (gmail_address and gmail_app_password and to_address):
        return False, "Email not sent: missing address or credentials."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to_address

    last_error = None
    for attempt in range(1, EMAIL_ATTEMPTS + 1):
        try:
            # STARTTLS on 587 rather than implicit SSL on 465: Gmail's
            # anti-abuse systems have been observed to silently stall
            # connections from cloud/CI IP ranges (like GitHub Actions) on
            # both ports, so this is retried a few times before giving up.
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(gmail_address, gmail_app_password)
                server.sendmail(gmail_address, [to_address], msg.as_string())
            return True, "Email sent."
        except Exception as exc:
            last_error = exc
            if attempt < EMAIL_ATTEMPTS:
                time.sleep(EMAIL_RETRY_DELAY_SECONDS)

    return False, f"Email failed after {EMAIL_ATTEMPTS} attempts: {last_error}"


def send_telegram(text, chat_id, bot_token):
    if not (chat_id and bot_token):
        return False, "Telegram not sent: missing chat id or bot token."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        response.raise_for_status()
        return True, "Telegram sent."
    except Exception as exc:
        return False, f"Telegram failed: {exc}"
