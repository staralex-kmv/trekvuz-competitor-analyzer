"""Парсинг сайтов конкурентов через Selenium + Chrome (вместо простого HTTP-запроса из исходного каркаса).

Браузер открывает страницу как живой пользователь, ждёт загрузки JS, прокручивает вниз (ленивые блоки),
снимает скриншот первого экрана, PDF всей страницы и видимый текст. Всё сохраняется в data/<slug>/.
chromedriver ставить не нужно — Selenium Manager (Selenium ≥ 4.6) скачивает его сам.
"""
import base64
import os
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

# Selenium говорит с chromedriver по localhost; системный HTTP(S)_PROXY не должен перехватывать этот трафик
os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY"), "localhost", "127.0.0.1"]))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def slugify(name: str) -> str:
    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  "a b v g d e e zh z i y k l m n o p r s t u f h ts ch sh sch _ y _ e yu ya".split()))
    name = "".join(tr.get(c, c) for c in name.lower())
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "site"


def _driver() -> webdriver.Chrome:
    opts = Options()
    if config.SELENIUM_HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument(f"--user-agent={UA}")
    opts.add_argument("--lang=ru-RU")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # не ждём счётчики и рекламу: DOM готов — работаем (иначе тяжёлые лендинги вешают рендерер на 30+ с)
    opts.page_load_strategy = "eager"
    drv = webdriver.Chrome(options=opts)
    drv.set_page_load_timeout(config.PAGE_TIMEOUT)
    return drv


# всплывающие квизы, cookie-баннеры и подписки закрывают лендинг на скриншоте — пробуем закрыть, как сделал бы человек
DISMISS_JS = """
const words = ['принять', 'понятно', 'хорошо', 'больше не показывать', 'закрыть', 'не сейчас', 'accept', 'ok'];
let n = 0;
document.querySelectorAll('button, a, [role=button], [aria-label]').forEach(el => {
  const t = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
  const visible = el.offsetParent !== null;
  if (visible && t.length < 30 && (words.includes(t) || t === '×' || t === '✕')) { try { el.click(); n++; } catch (e) {} }
});
return n;
"""


def _dismiss_overlays(drv) -> int:
    from selenium.webdriver.common.keys import Keys
    try:
        drv.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass
    try:
        return drv.execute_script(DISMISS_JS) or 0
    except Exception:
        return 0


def fetch(url: str, competitor: str, attempts: int = 2) -> dict:
    """Открывает страницу (с повтором при таймауте) и сохраняет скриншот, PDF и текст."""
    for i in range(attempts):
        try:
            return _fetch_once(url, competitor)
        except TimeoutException:
            if i == attempts - 1:
                raise
            time.sleep(3)


def _fetch_once(url: str, competitor: str) -> dict:
    out = config.DATA_DIR / slugify(competitor or url)
    out.mkdir(parents=True, exist_ok=True)
    drv = _driver()
    try:
        try:
            drv.get(url)
        except TimeoutException:
            drv.execute_script("window.stop();")  # что успело загрузиться — то и анализируем
        WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)  # SPA дорисовывают контент после готовности DOM
        # прокрутка до конца и обратно — подгружаем ленивые блоки
        for y in range(0, 6):
            drv.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {y} / 5);")
            time.sleep(0.6)
        drv.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        if _dismiss_overlays(drv):
            time.sleep(1)

        screenshot = out / "landing.png"
        drv.save_screenshot(str(screenshot))
        pdf = out / "page.pdf"
        pdf.write_bytes(base64.b64decode(drv.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})["data"]))
        text = drv.find_element(By.TAG_NAME, "body").text
        text = re.sub(r"\n{2,}", "\n", text).strip()
        (out / "page.txt").write_text(text, encoding="utf-8")
        return {"title": drv.title, "final_url": drv.current_url, "screenshot": screenshot,
                "pdf": pdf, "text": text}
    finally:
        drv.quit()


STUB_MARKERS = {"vpn": "просит отключить VPN", "captcha": "капча", "не робот": "проверка «я не робот»",
                "access denied": "доступ запрещён", "403 forbidden": "доступ запрещён"}


def stub_reason(text: str) -> str:
    """Признаки страницы-заглушки вместо сайта: очень мало текста или маркер антибот-защиты."""
    low = text.lower()
    for marker, reason in STUB_MARKERS.items():
        if marker in low and len(text) < 1500:
            return reason
    return "почти нет текста" if len(text) < 300 else ""


def rel(path: Path) -> str:
    return str(path.relative_to(config.BASE_DIR)) if path else ""
