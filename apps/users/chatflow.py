import re, requests
from django.conf import settings

class ChatFlowError(Exception): pass

def _phone_to_jid(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone))
    if not digits.startswith("996"):
        raise ChatFlowError("phone_must_start_with_996")
    return f"{digits}@c.us"

def chatflow_send_text(phone: str, msg: str) -> None:
    jid = _phone_to_jid(phone)
    url = "https://lk.chatflow.kz/api/v1/send-text"
    params = {
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJoMzVsalJCWVllblM1Z05HOTdXRlBJSkdkeUlnVWdBQSIsInJvbGUiOiJ1c2VyIiwiaWF0IjoxNzc4NDk5NTc4fQ.gYUTo2934PSGWTUOH1wkcOJq6Fbnp7r2gAdd4FdShn8",
        "instance_id": settings.CHATFLOW_INSTANCE_ID.strip(), 
        "jid": jid,
        "msg": msg,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
    except requests.RequestException as e:
        raise ChatFlowError(f"net_error: {e}") from e

    try:
        data = r.json()
    except ValueError:
        raise ChatFlowError(f"bad_json({r.status_code}): {r.text[:300]}")

    if data is True or data.get("success") is True:
        return

    err = data.get("message") or data.get("error") or data.get("response") or r.text
    raise ChatFlowError(f"api_error: {err}")
