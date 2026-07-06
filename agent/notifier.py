"""Send notifications by Email (Gmail SMTP) and Telegram (Bot API)."""
import smtplib
from email.mime.text import MIMEText

import requests


def send_email(subject, body, to_address, gmail_address, gmail_app_password):
    if not (gmail_address and gmail_app_password and to_address):
        return False, "Email not sent: missing address or credentials."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to_address

    try:
        # STARTTLS on 587 rather than implicit SSL on 465: more reliable from
        # GitHub Actions runners, where 465 connections have been observed to
        # drop mid-handshake.
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, [to_address], msg.as_string())
        return True, "Email sent."
    except Exception as exc:
        return False, f"Email failed: {exc}"


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
