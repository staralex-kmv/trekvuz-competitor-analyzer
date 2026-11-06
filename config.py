"""Настройки приложения. Секреты — только в .env (в .gitignore) или в macOS Keychain, в код не попадают."""
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# в собранном PyInstaller-приложении файлы лежат во временной папке _MEIPASS, а .env и data/ — рядом с исполняемым файлом
if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _from_keychain(account: str, service: str) -> str:
    """Запасной путь для Mac владельца: ключ лежит в Keychain, .env не нужен."""
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


# --- LLM: GigaChat (бесплатный тариф Freemium) вместо OpenAI GPT-4o из урока ---
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY") or _from_keychain("trekvuz", "gigachat-trekvuz-authkey")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
# Max, а не Lite: на одном и том же тексте GigaChat-2 давал доверие 8/7/4, Max — 6/6/6 (data/stability_postupashkin.json)
GIGACHAT_TEXT_MODEL = os.getenv("GIGACHAT_TEXT_MODEL", "GigaChat-2-Max")
# картинки GigaChat понимает через attachments; в моделях Pro/Max качество заметно выше
GIGACHAT_VISION_MODEL = os.getenv("GIGACHAT_VISION_MODEL", "GigaChat-2-Max")
CA_CERT = BUNDLE_DIR / "certs" / "russian_trusted_ca.pem"

# --- Сервер ---
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# --- История ---
HISTORY_FILE = BASE_DIR / "data" / "history.json"
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "50"))

# --- Данные и парсинг ---
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BUNDLE_DIR / "frontend"
SELENIUM_HEADLESS = os.getenv("SELENIUM_HEADLESS", "1") == "1"
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "40"))
MAX_PAGE_TEXT = 6000  # символов текста страницы в промпт — чтобы уложиться в контекст и лимит Freemium

# Ниша: сервисы подбора вуза для абитуриентов. Мы — «Трек ВУЗ» (Telegram/MAX-бот, платное исследование поступления
# по официальным документам вузов). Конкуренты — то, чем абитуриент пользуется вместо нас.
OUR_PRODUCT = (
    "«Трек ВУЗ» — Telegram/MAX-бот: анкета абитуриента → направление → вузы в городах заказчика → данные только с "
    "официальных сайтов вузов (бюджетные и целевые места, стоимость, проходной балл) со ссылкой на документ → "
    "два PDF (отчёт + план подготовки). Платно, от 1 000 ₽. Принцип: ни одного выдуманного значения."
)
COMPETITOR_URLS = {
    "Поступашкин": "https://www.postupashkin.ru/",
    "ВУЗопедия": "https://vuzopedia.ru/",
    "Табитуриент": "https://tabiturient.ru/",
    "Postupi.online": "https://postupi.online/",
    "Учёба.ру": "https://www.ucheba.ru/",
}
