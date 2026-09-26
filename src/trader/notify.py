"""Envio de mensagem no Telegram. Falha de envio nunca derruba o bot."""
import httpx

from trader.config import load_secrets


def notify(text: str, secrets: dict | None = None) -> bool:
    s = secrets or load_secrets()
    if not s["TELEGRAM_BOT_TOKEN"] or not s["TELEGRAM_CHAT_ID"]:
        return False
    try:
        httpx.post(f"https://api.telegram.org/bot{s['TELEGRAM_BOT_TOKEN']}/sendMessage",
                   json={"chat_id": s["TELEGRAM_CHAT_ID"], "text": text[:4000]}, timeout=10)
        return True
    except Exception:
        return False
