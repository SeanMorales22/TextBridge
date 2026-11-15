"""SMS provider integration: SMS Gateway for Android (https://sms-gate.app).

The gateway is an Android app that turns a phone into an SMS gateway with a
REST API. Messages are sent from the phone's own SIM card. It works in two modes
that share the same API:

* Cloud mode  - SMSGATE_URL=https://api.sms-gate.app/3rdparty/v1
* Local mode  - SMSGATE_URL=http://<phone-ip>:8080   (same Wi-Fi network)

Endpoints used (HTTP Basic Auth):
* POST {SMSGATE_URL}/messages       - enqueue a message, returns 202 + state
* GET  {SMSGATE_URL}/messages/{id}  - read the current state

Views never call the API directly; they call ``send_sms`` / ``fetch_status``,
which always return an ``SmsResult`` instead of raising. Every failure becomes a
short, friendly message that never contains the username or password.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class SmsResult:
    ok: bool
    status: str  # one of SmsMessage.Status values ("" = unknown / do not change)
    sid: str = ""
    num_segments: int | None = None
    error_code: str = ""
    user_message: str = ""


class ProviderNotConfigured(Exception):
    pass


# Gateway processing states -> our SmsMessage.Status values.
GATEWAY_STATES = {
    "pending": "queued",      # stored by the gateway, waiting for the phone
    "processed": "processed",  # the phone handed it to Android's SMS API
    "sent": "sent",            # the carrier's SMS centre accepted it
    "delivered": "delivered",  # the recipient's handset confirmed receipt
    "failed": "failed",
    "cancelling": "canceled",
    "cancelled": "canceled",
}

HTTP_ERROR_MESSAGES = {
    400: "The SMS gateway rejected the request",
    401: "The SMS gateway rejected the username or password. Check SMSGATE_USERNAME and SMSGATE_PASSWORD.",
    403: "The SMS gateway account is not allowed to do this. Check SMSGATE_USERNAME and SMSGATE_PASSWORD.",
    404: "The SMS gateway address is wrong or the message no longer exists. Check SMSGATE_URL.",
    409: "The SMS gateway already has a message with this ID.",
    503: "The SMS gateway queue is full or no phone is online. Make sure the gateway phone is on, connected and the app is running.",
}


def is_configured():
    return bool(settings.SMSGATE_URL and settings.SMSGATE_USERNAME and settings.SMSGATE_PASSWORD)


def _base_url():
    if not is_configured():
        raise ProviderNotConfigured()
    return settings.SMSGATE_URL.rstrip("/")


def _auth():
    return (settings.SMSGATE_USERNAME, settings.SMSGATE_PASSWORD)


def _gateway_error_text(response):
    """The ``message`` field of the gateway's ErrorResponse JSON, if any."""
    try:
        text = str(response.json().get("message", "")).strip()
    except (ValueError, AttributeError):
        return ""
    # Never echo anything that could contain our credentials.
    for secret in (settings.SMSGATE_USERNAME, settings.SMSGATE_PASSWORD):
        if secret and secret in text:
            return ""
    return text[:200]


def _http_error_result(response, action):
    code = response.status_code
    logger.warning("%s failed: gateway returned HTTP %s", action, code)
    if code == 400:
        detail = _gateway_error_text(response)
        message = HTTP_ERROR_MESSAGES[400] + (f": {detail}" if detail else ".")
    elif code in HTTP_ERROR_MESSAGES:
        message = HTTP_ERROR_MESSAGES[code]
    elif code >= 500:
        message = "The SMS gateway is having problems right now. Please try again later."
    else:
        message = f"The SMS gateway returned an unexpected response (HTTP {code})."
    # 400/409 mean the gateway understood us and refused this message;
    # everything else means the message never got into the gateway.
    status = "rejected" if code in (400, 409) else "error"
    return SmsResult(ok=False, status=status, error_code=f"HTTP {code}", user_message=message)


def _exception_result(exc, action):
    if isinstance(exc, ProviderNotConfigured):
        logger.warning("%s skipped: SMS gateway is not configured.", action)
        return SmsResult(
            ok=False,
            status="error",
            error_code="CONFIG",
            user_message=(
                "The SMS gateway is not configured. Set SMSGATE_URL, SMSGATE_USERNAME "
                "and SMSGATE_PASSWORD in your .env file."
            ),
        )
    if isinstance(exc, requests.exceptions.Timeout):
        logger.warning("%s failed: gateway request timed out.", action)
        return SmsResult(
            ok=False,
            status="error",
            error_code="TIMEOUT",
            user_message="The SMS gateway did not respond in time. Check your internet connection and that the gateway phone is online.",
        )
    if isinstance(exc, requests.exceptions.RequestException):
        logger.warning("%s failed: network error (%s).", action, type(exc).__name__)
        return SmsResult(
            ok=False,
            status="error",
            error_code="NETWORK",
            user_message=(
                "Could not connect to the SMS gateway. Check your internet connection "
                "(in local mode, make sure the computer and phone are on the same Wi-Fi)."
            ),
        )
    logger.exception("%s failed with an unexpected error.", action)
    return SmsResult(
        ok=False,
        status="error",
        error_code="UNKNOWN",
        user_message="An unexpected error occurred while contacting the SMS gateway.",
    )


# Hints for common Android send errors reported by the gateway phone.
PHONE_ERROR_HINTS = {
    "RESULT_MODEM_ERROR": "Check the gateway phone's load/promo, signal, and default SIM for messages.",
    "RESULT_ERROR_GENERIC_FAILURE": "Check the gateway phone's load/promo and signal.",
    "RESULT_ERROR_NO_SERVICE": "The gateway phone has no mobile signal.",
    "RESULT_ERROR_RADIO_OFF": "The gateway phone's mobile radio is off (airplane mode?).",
    "RESULT_ERROR_LIMIT_EXCEEDED": "The phone or carrier limited how many texts can be sent. Wait a few minutes.",
}


def _phone_failure_message(reason):
    message = "The gateway phone could not send the message" + (f": {reason}" if reason else ".")
    for code, hint in PHONE_ERROR_HINTS.items():
        if code in (reason or ""):
            return f"{message} {hint}"
    return message


def _parse_state(data):
    """Return (our_status, failure_reason) from a gateway MessageState JSON."""
    state = str(data.get("state", "")).lower()
    status = GATEWAY_STATES.get(state, "")
    reason = ""
    for recipient in data.get("recipients") or []:
        if recipient.get("error"):
            reason = str(recipient["error"])[:200]
            break
    return status, reason


def send_sms(to: str, body: str) -> SmsResult:
    """Submit an SMS to the gateway. ``to`` must already be validated E.164."""
    payload = {
        "textMessage": {"text": body},
        "phoneNumbers": [to],
        "withDeliveryReport": True,
    }
    if settings.SMSGATE_SIM_NUMBER:
        payload["simNumber"] = settings.SMSGATE_SIM_NUMBER

    try:
        response = requests.post(
            _base_url() + "/messages",
            json=payload,
            auth=_auth(),
            timeout=settings.SMSGATE_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes an SmsResult
        return _exception_result(exc, "send_sms")

    if response.status_code not in (200, 201, 202):
        return _http_error_result(response, "send_sms")

    try:
        data = response.json()
    except ValueError:
        logger.warning("send_sms: gateway returned a non-JSON success response.")
        data = {}

    status, reason = _parse_state(data)
    message_id = str(data.get("id", ""))[:64]
    if status == "failed":
        return SmsResult(
            ok=False,
            status="failed",
            sid=message_id,
            error_code="FAILED",
            user_message=_phone_failure_message(reason),
        )

    status = status or "queued"
    logger.info("SMS submitted to gateway: id=%s state=%s", message_id, status)
    return SmsResult(
        ok=True,
        status=status,
        sid=message_id,
        user_message=(
            "Message submitted to the SMS gateway (status: %s). Delivery is not confirmed yet."
            % status
        ),
    )


def fetch_status(message_id: str) -> SmsResult:
    """Ask the gateway for the latest state of a previously submitted message."""
    try:
        response = requests.get(
            f"{_base_url()}/messages/{requests.utils.quote(message_id, safe='')}",
            auth=_auth(),
            timeout=settings.SMSGATE_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        result = _exception_result(exc, "fetch_status")
        result.status = ""  # a failed lookup must not overwrite the stored status
        return result

    if response.status_code != 200:
        result = _http_error_result(response, "fetch_status")
        result.status = ""
        return result

    try:
        data = response.json()
    except ValueError:
        return SmsResult(ok=False, status="", error_code="BAD_RESPONSE",
                         user_message="The SMS gateway returned an unreadable response.")

    status, reason = _parse_state(data)
    result = SmsResult(ok=True, status=status, sid=message_id)
    if status == "failed":
        result.error_code = "FAILED"
        result.user_message = _phone_failure_message(reason)
    return result
