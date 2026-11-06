"""Конвейер парсинга, общий для веба (/parse/demo) и desktop: Selenium → скриншот + PDF + текст →
ИИ-анализ текста и скриншота → запись в историю."""
from models.schemas import ParsingResult
from services import parsing_service
from services.gigachat_service import get_service
from services.history_service import history


def run_parse(competitor: str, url: str) -> ParsingResult:
    res = ParsingResult(competitor=competitor, url=url)
    try:
        page = parsing_service.fetch(url, competitor)
    except Exception as e:
        res.error = f"Не удалось открыть страницу: {type(e).__name__}: {str(e).splitlines()[0][:200]}"
        return res
    res.title, res.url = page["title"], page["final_url"]
    res.screenshot, res.pdf = parsing_service.rel(page["screenshot"]), parsing_service.rel(page["pdf"])
    res.text_chars = len(page["text"])
    stub = parsing_service.stub_reason(page["text"])
    if stub:
        # заглушку («отключите VPN», капча) не анализируем: модель честно оценит её как «минималистичный дизайн»
        res.error = f"Вместо сайта — заглушка ({stub}); анализ пропущен, скриншот сохранён"
        history.add("parse", res.model_dump(), competitor, res.url, 0)
        return res
    tokens = 0
    svc = get_service()
    errors = []
    try:
        res.text_analysis, t = svc.analyze_text(f"Сайт {competitor} ({res.url}), «{res.title}»:\n{page['text']}")
        tokens += t
    except Exception as e:
        errors.append(f"текст: {e}")
    try:
        res.image_analysis, t = svc.analyze_image(page["screenshot"])
        tokens += t
    except Exception as e:
        errors.append(f"скриншот: {e}")
    res.error = "; ".join(errors)
    history.add("parse", res.model_dump(), competitor, res.url, tokens)
    return res
