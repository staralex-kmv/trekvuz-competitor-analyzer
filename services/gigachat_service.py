"""Сервис ИИ-анализа на GigaChat — замена openai_service.py из урока (GPT-4o / GPT-4V).

Почему GigaChat: бесплатный тариф Freemium, работает из РФ без прокси, понимает изображения (attachments).
SSL не отключаем: у серверов Сбера сертификат УЦ Минцифры, добавляем его к корням certifi.
"""
import json
import re
import tempfile
import time
import uuid
from pathlib import Path

import certifi
import requests
from pypdf import PdfReader

import config
from models.schemas import CompetitionAnalysis, ImageAnalysis

AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BASE_URL = "https://api.giga.chat/v1"

TEXT_PROMPT = f"""Ты — эксперт по конкурентному анализу рынка услуг для абитуриентов (подбор вуза, проходные баллы, бюджетные места).
Наш продукт: {config.OUR_PRODUCT}
Проанализируй текст конкурента и верни СТРОГО JSON без пояснений и без markdown:
{{
  "strengths": ["сильная сторона 1", "..."],
  "weaknesses": ["слабая сторона 1", "..."],
  "unique_offers": ["уникальное предложение конкурента 1", "..."],
  "recommendations": ["что сделать Трек ВУЗ 1", "..."],
  "summary": "краткое резюме, 2–3 предложения",
  "data_trust_score": 5,
  "data_trust_reason": "почему такая оценка",
  "threat_level": 5
}}
Правила:
- в каждом массиве 3–5 пунктов, по-русски, конкретно;
- recommendations — действия для команды Трек ВУЗ (что перенять, чем отстроиться, что сказать в рекламе), НЕ советы конкуренту;
- data_trust_score от 0 до 10 — насколько цифрам конкурента можно верить. Шкала: 9–10 — у цифр есть ссылка на документ вуза (приказ, правила приёма) и год;
  6–8 — назван источник (сайт вуза, Минобрнауки) без ссылки на документ; 3–5 — цифры есть, источник не назван; 0–2 — цифр нет или они рекламные;
  рейтинги (QS, RAEX и т.п.) и «наши данные» — не официальный документ вуза;
- threat_level от 0 до 10 — насколько конкурент закрывает ту же потребность абитуриента, что и Трек ВУЗ;
- опирайся только на текст; если чего-то в тексте нет — так и пиши «в тексте не указано», не придумывай;
- о Трек ВУЗ знай только то, что написано выше: он НЕ гарантирует поступление и НЕ сопровождает абитуриента лично — не приписывай ему этого;
- если текст — заглушка, ошибка или защита от ботов, а не страница сервиса, верни пустые массивы и summary «страница не загрузилась»."""

IMAGE_PROMPT = f"""Ты — эксперт по визуальному маркетингу и UX. На изображении — скриншот сайта сервиса для абитуриентов (конкурент).
Наш продукт: {config.OUR_PRODUCT}
Верни СТРОГО JSON без пояснений и без markdown:
{{
  "description": "что изображено: блоки, заголовок, призыв к действию",
  "marketing_insights": ["инсайт 1", "..."],
  "visual_style_score": 7,
  "design_score": 7,
  "visual_style_analysis": "цвет, типографика, композиция",
  "trust_signals": ["что вызывает доверие у родителя абитуриента: отзывы, лицензии, цифры, логотипы вузов", "..."],
  "trust_score": 5,
  "recommendations": ["что взять или сделать лучше в Трек ВУЗ", "..."]
}}
Правила:
- visual_style_score, design_score, trust_score — целые от 0 до 10; design_score — удобство: понятно ли за 5 секунд, что сделать;
- в каждом массиве 3–5 пунктов, по-русски;
- описывай только то, что видно на изображении; не придумывай текст, который не читается; слова «предположительно», «возможно» — признак выдумки, такой пункт не пиши;
- trust_signals — только реально видимые элементы (цифры, отзывы с рейтингом, логотипы, лицензия); если их нет — пустой массив и trust_score 0–2;
- recommendations — про сайт/лендинг Трек ВУЗ (trekvuz.ru) и его подачу, а не про интерфейс конкурента;
- если на скриншоте заглушка, ошибка или проверка «я не робот» — все оценки 0 и description «страница не загрузилась»."""


def _ca_bundle() -> str:
    """certifi + russian_trusted_ca.pem одним файлом — requests принимает только путь."""
    bundle = Path(tempfile.gettempdir()) / "competitors_ca_bundle.pem"
    bundle.write_text(Path(certifi.where()).read_text() + "\n" + config.CA_CERT.read_text())
    return str(bundle)


def extract_json(content: str) -> dict:
    """Модель иногда оборачивает JSON в ```json ... ``` или добавляет текст — берём первый объект {...}."""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError(f"В ответе модели нет JSON: {content[:300]}")
    return json.loads(m.group(0))


def _clamp_scores(data: dict, keys: tuple[str, ...]) -> dict:
    for k in keys:
        try:
            data[k] = max(0, min(10, int(data.get(k, 0))))
        except (TypeError, ValueError):
            data[k] = 0
    return data


class GigaChatService:
    def __init__(self):
        if not config.GIGACHAT_AUTH_KEY:
            raise RuntimeError("Нет ключа GigaChat: добавьте GIGACHAT_AUTH_KEY в .env (см. .env.example)")
        self.verify = _ca_bundle()
        self._token = None
        self._token_exp = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = requests.post(
            AUTH_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {config.GIGACHAT_AUTH_KEY}",  # ключ из кабинета уже в Base64
            },
            data={"scope": config.GIGACHAT_SCOPE},
            verify=self.verify,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = float(data["expires_at"]) / 1000
        return self._token

    def _chat(self, model: str, messages: list[dict]) -> tuple[str, int]:
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.2},
            verify=self.verify,
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GigaChat {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data["choices"][0]["message"]["content"], data.get("usage", {}).get("total_tokens", 0)

    def _upload(self, path: Path) -> str:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        with path.open("rb") as f:
            r = requests.post(
                f"{BASE_URL}/files",
                headers={"Authorization": f"Bearer {self._get_token()}"},
                files={"file": (path.name, f, mime)},
                data={"purpose": "general"},
                verify=self.verify,
                timeout=60,
            )
        if r.status_code >= 400:
            raise RuntimeError(f"GigaChat /files {r.status_code}: {r.text[:300]}")
        return r.json()["id"]

    # --- три метода анализа, как в уроке, + PDF ---
    def analyze_text(self, text: str) -> tuple[CompetitionAnalysis, int]:
        content, tokens = self._chat(
            config.GIGACHAT_TEXT_MODEL,
            [{"role": "system", "content": TEXT_PROMPT},
             {"role": "user", "content": text[: config.MAX_PAGE_TEXT]}],
        )
        data = _clamp_scores(extract_json(content), ("data_trust_score", "threat_level"))
        return CompetitionAnalysis(**data), tokens

    def analyze_image(self, path: Path) -> tuple[ImageAnalysis, int]:
        file_id = self._upload(path)
        content, tokens = self._chat(
            config.GIGACHAT_VISION_MODEL,
            [{"role": "system", "content": IMAGE_PROMPT},
             {"role": "user", "content": "Проанализируй этот скриншот конкурента.", "attachments": [file_id]}],
        )
        data = _clamp_scores(extract_json(content), ("visual_style_score", "design_score", "trust_score"))
        return ImageAnalysis(**data), tokens

    def analyze_pdf(self, path: Path) -> tuple[CompetitionAnalysis, int, int]:
        """Текст из PDF достаём локально (pypdf) — дешевле и предсказуемее, чем отдавать файл модели целиком."""
        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if len(text) < 50:
            raise ValueError("В PDF нет текстового слоя (скан) — нужен OCR, в MVP не реализован")
        analysis, tokens = self.analyze_text(text)
        return analysis, tokens, len(text)


_service: GigaChatService | None = None


def get_service() -> GigaChatService:
    global _service
    if _service is None:
        _service = GigaChatService()
    return _service
