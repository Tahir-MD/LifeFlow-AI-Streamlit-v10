"""
Delivery of SMS, WhatsApp and email. Every provider is OPTIONAL: if its settings are missing, the
function returns False and does nothing, so the app (and OTP testing) never depends on any account.

Several ways to send, chosen only by which settings exist in backend/.env:

SMS (first one that is set up is used)
  1. Your own HTTP gateway  -> SMS_GATEWAY_URL ...   (an Android phone running an SMS-gateway app,
                                                       or any Pakistani SMS company's web API)
  2. Twilio                 -> TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER

WhatsApp
  1. Meta WhatsApp Cloud API -> WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  2. Twilio                  -> TWILIO_WHATSAPP_FROM (+ the Twilio settings above)

Email
  1. SMTP (Gmail works)      -> SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
  2. SendGrid                -> SENDGRID_API_KEY, SENDGRID_FROM_EMAIL

See README.md for step-by-step setup of each one.
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage

# ---------------------------------------------------------------- settings
def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


TWILIO_ACCOUNT_SID = _env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = _env("TWILIO_FROM_NUMBER")
TWILIO_WHATSAPP_FROM = _env("TWILIO_WHATSAPP_FROM")

# Own SMS gateway (Android phone app or a local SMS company's web API)
SMS_GATEWAY_URL = _env("SMS_GATEWAY_URL")
SMS_GATEWAY_AUTH = _env("SMS_GATEWAY_AUTH")        # "user:password" (basic) or "bearer:TOKEN" or "header:Name:value"
SMS_GATEWAY_BODY = _env("SMS_GATEWAY_BODY", '{"to": "{to}", "message": "{message}"}')
SMS_GATEWAY_FORMAT = _env("SMS_GATEWAY_FORMAT", "json").lower()   # "json" or "form"
SMS_GATEWAY_METHOD = _env("SMS_GATEWAY_METHOD", "POST").upper()   # "POST" or "GET"
SMS_GATEWAY_TIMEOUT = int(_env("SMS_GATEWAY_TIMEOUT", "15") or 15)
SMS_GATEWAY_VERIFY_TLS = _env("SMS_GATEWAY_VERIFY_TLS", "on").lower() != "off"

# Meta WhatsApp Cloud API
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_VERSION = _env("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_OTP_TEMPLATE = _env("WHATSAPP_OTP_TEMPLATE")        # an approved "authentication" template
WHATSAPP_OTP_TEMPLATE_LANG = _env("WHATSAPP_OTP_TEMPLATE_LANG", "en_US")
WHATSAPP_OTP_COPY_BUTTON = _env("WHATSAPP_OTP_COPY_BUTTON", "on").lower() != "off"
WHATSAPP_ALERT_TEMPLATE = _env("WHATSAPP_ALERT_TEMPLATE")    # optional template with ONE text variable {{1}}
WHATSAPP_ALERT_TEMPLATE_LANG = _env("WHATSAPP_ALERT_TEMPLATE_LANG", "en_US")

# Email
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587") or 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD").replace(" ", "")   # Gmail shows app passwords with spaces
SMTP_FROM = _env("SMTP_FROM") or SMTP_USER
SENDGRID_API_KEY = _env("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = _env("SENDGRID_FROM_EMAIL", "alerts@lifeflow.app")


# ---------------------------------------------------------------- status
def is_gateway_sms_configured() -> bool:
    return bool(SMS_GATEWAY_URL)


def is_twilio_sms_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


def is_sms_configured() -> bool:
    return is_gateway_sms_configured() or is_twilio_sms_configured()


def is_cloud_whatsapp_configured() -> bool:
    return bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID)


def is_twilio_whatsapp_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM)


def is_whatsapp_configured() -> bool:
    return is_cloud_whatsapp_configured() or is_twilio_whatsapp_configured()


def is_smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def is_email_configured() -> bool:
    return is_smtp_configured() or bool(SENDGRID_API_KEY)


# ---------------------------------------------------------------- SMS
def _fill(node, values: dict):
    """Replaces {to} and {message} inside every string of a JSON structure (safe: no manual quoting)."""
    if isinstance(node, str):
        for key, value in values.items():
            node = node.replace("{" + key + "}", value)
        return node
    if isinstance(node, list):
        return [_fill(item, values) for item in node]
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    return node


def _gateway_auth():
    """Returns (basic_auth_tuple or None, extra_headers dict) from SMS_GATEWAY_AUTH."""
    if not SMS_GATEWAY_AUTH:
        return None, {}
    lowered = SMS_GATEWAY_AUTH.lower()
    if lowered.startswith("bearer:"):
        return None, {"Authorization": f"Bearer {SMS_GATEWAY_AUTH[7:]}"}
    if lowered.startswith("header:"):
        parts = SMS_GATEWAY_AUTH.split(":", 2)
        if len(parts) == 3:
            return None, {parts[1]: parts[2]}
        return None, {}
    if ":" in SMS_GATEWAY_AUTH:
        user, password = SMS_GATEWAY_AUTH.split(":", 1)
        return (user, password), {}
    return None, {}


def _send_sms_gateway(to_phone_number: str, message: str) -> bool:
    import requests

    values = {"to": to_phone_number, "to_plain": to_phone_number.lstrip("+"), "message": message}
    basic, headers = _gateway_auth()
    kwargs = {"timeout": SMS_GATEWAY_TIMEOUT, "verify": SMS_GATEWAY_VERIFY_TLS, "auth": basic, "headers": headers}
    if SMS_GATEWAY_METHOD == "GET":
        # For GET gateways the body setting holds the query string as JSON: {"user":"x","to":"{to}","text":"{message}"}
        kwargs["params"] = _fill(json.loads(SMS_GATEWAY_BODY), values)
        response = requests.get(SMS_GATEWAY_URL, **kwargs)
    elif SMS_GATEWAY_FORMAT == "form":
        kwargs["data"] = _fill(json.loads(SMS_GATEWAY_BODY), values)
        response = requests.post(SMS_GATEWAY_URL, **kwargs)
    else:
        kwargs["json"] = _fill(json.loads(SMS_GATEWAY_BODY), values)
        response = requests.post(SMS_GATEWAY_URL, **kwargs)
    return response.status_code < 300


def _send_sms_twilio(to_phone_number: str, message: str) -> bool:
    from twilio.rest import Client
    Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=to_phone_number)
    return True


def send_sms(to_phone_number: str, message: str) -> bool:
    """Sends one SMS. Returns False (never raises) if no provider is set up or the send fails."""
    if not to_phone_number or not is_sms_configured():
        return False
    if is_gateway_sms_configured():
        try:
            if _send_sms_gateway(to_phone_number, message):
                return True
        except Exception:  # noqa: BLE001 -- a delivery failure must never break the request that triggered it
            pass
    if is_twilio_sms_configured():
        try:
            return _send_sms_twilio(to_phone_number, message)
        except Exception:  # noqa: BLE001
            return False
    return False


# ---------------------------------------------------------------- WhatsApp
def _cloud_post(payload: dict) -> bool:
    import requests
    response = requests.post(
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=12,
    )
    return response.status_code < 300


def send_whatsapp_otp(to_phone_number: str, code: str) -> bool:
    """
    Sends a verification code on WhatsApp. WhatsApp only lets a business START a chat with an
    approved TEMPLATE, so a Cloud API template (WHATSAPP_OTP_TEMPLATE) is used when it is set.
    """
    if not to_phone_number or not is_whatsapp_configured():
        return False
    if is_cloud_whatsapp_configured() and WHATSAPP_OTP_TEMPLATE:
        try:
            components = [{"type": "body", "parameters": [{"type": "text", "text": code}]}]
            if WHATSAPP_OTP_COPY_BUTTON:   # authentication templates carry a "copy code" button
                components.append({"type": "button", "sub_type": "url", "index": "0",
                                   "parameters": [{"type": "text", "text": code}]})
            return _cloud_post({
                "messaging_product": "whatsapp", "to": to_phone_number.lstrip("+"), "type": "template",
                "template": {"name": WHATSAPP_OTP_TEMPLATE, "language": {"code": WHATSAPP_OTP_TEMPLATE_LANG},
                             "components": components},
            })
        except Exception:  # noqa: BLE001
            return False
    return send_whatsapp(to_phone_number, f"LifeFlow: your verification code is {code}. Do not share it.")


def send_whatsapp(to_phone_number: str, message: str) -> bool:
    """Sends one WhatsApp message. Returns False (never raises) if not set up or it fails."""
    if not to_phone_number or not is_whatsapp_configured():
        return False
    if is_cloud_whatsapp_configured():
        try:
            if WHATSAPP_ALERT_TEMPLATE:
                payload = {
                    "messaging_product": "whatsapp", "to": to_phone_number.lstrip("+"), "type": "template",
                    "template": {"name": WHATSAPP_ALERT_TEMPLATE, "language": {"code": WHATSAPP_ALERT_TEMPLATE_LANG},
                                 "components": [{"type": "body", "parameters": [{"type": "text", "text": message[:900]}]}]},
                }
            else:  # plain text: WhatsApp delivers it only if the person messaged your number in the last 24 hours
                payload = {"messaging_product": "whatsapp", "to": to_phone_number.lstrip("+"), "type": "text",
                           "text": {"preview_url": False, "body": message[:1500]}}
            if _cloud_post(payload):
                return True
        except Exception:  # noqa: BLE001
            pass
    if is_twilio_whatsapp_configured():
        try:
            from twilio.rest import Client
            sender = TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_FROM.startswith("whatsapp:") else f"whatsapp:{TWILIO_WHATSAPP_FROM}"
            Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(body=message, from_=sender, to=f"whatsapp:{to_phone_number}")
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


# ---------------------------------------------------------------- Email
def _send_email_smtp(to_email: str, subject: str, body: str) -> bool:
    message = EmailMessage()
    message["From"] = f"LifeFlow <{SMTP_FROM}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    return True


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Sends one email (SMTP/Gmail first, then SendGrid). Returns False (never raises) if not set up or it fails."""
    if not to_email or not is_email_configured():
        return False
    if is_smtp_configured():
        try:
            return _send_email_smtp(to_email, subject, body)
        except Exception:  # noqa: BLE001
            if not SENDGRID_API_KEY:
                return False
    if SENDGRID_API_KEY:
        try:
            import requests
            response = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
                json={"personalizations": [{"to": [{"email": to_email}]}], "from": {"email": SENDGRID_FROM_EMAIL},
                      "subject": subject, "content": [{"type": "text/plain", "value": body}]},
                timeout=8,
            )
            return response.status_code < 300
        except Exception:  # noqa: BLE001
            return False
    return False


def delivery_status() -> dict:
    return {
        "sms_configured": is_sms_configured(),
        "sms_provider": "gateway" if is_gateway_sms_configured() else ("twilio" if is_twilio_sms_configured() else None),
        "whatsapp_configured": is_whatsapp_configured(),
        "whatsapp_provider": "cloud" if is_cloud_whatsapp_configured() else ("twilio" if is_twilio_whatsapp_configured() else None),
        "email_configured": is_email_configured(),
        "email_provider": "smtp" if is_smtp_configured() else ("sendgrid" if SENDGRID_API_KEY else None),
    }
