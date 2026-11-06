"""Модели запросов и ответов. Поля ответов совпадают с JSON, который мы требуем от модели в промптах."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- запросы ---
class TextRequest(BaseModel):
    text: str = Field(..., min_length=20, description="Текст конкурента: описание продукта, тарифы, лендинг")
    competitor: str = Field("", description="Название конкурента (для истории)")


class ParseRequest(BaseModel):
    url: Optional[str] = Field(None, description="Адрес страницы; без него — все конкуренты из config.COMPETITOR_URLS")
    competitor: str = ""


# --- ответы ИИ ---
class CompetitionAnalysis(BaseModel):
    strengths: list[str] = []
    weaknesses: list[str] = []
    unique_offers: list[str] = []
    recommendations: list[str] = []
    summary: str = ""
    # поля под нишу «подбор вуза»: насколько цифрам можно верить и насколько конкурент опасен для Трек ВУЗ
    data_trust_score: int = Field(0, ge=0, le=10)
    data_trust_reason: str = ""
    threat_level: int = Field(0, ge=0, le=10)


class ImageAnalysis(BaseModel):
    description: str = ""
    marketing_insights: list[str] = []
    visual_style_score: int = Field(0, ge=0, le=10)
    design_score: int = Field(0, ge=0, le=10)
    visual_style_analysis: str = ""
    trust_signals: list[str] = []
    trust_score: int = Field(0, ge=0, le=10)
    recommendations: list[str] = []


class ParsingResult(BaseModel):
    competitor: str
    url: str
    title: str = ""
    screenshot: str = ""  # путь к PNG в data/
    pdf: str = ""  # снимок страницы в PDF (Chrome print) — источник для /analyze/pdf
    text_chars: int = 0
    text_analysis: Optional[CompetitionAnalysis] = None
    image_analysis: Optional[ImageAnalysis] = None
    error: str = ""


# --- история ---
class HistoryItem(BaseModel):
    id: int
    created_at: datetime
    kind: Literal["text", "image", "pdf", "parse"]
    competitor: str = ""
    input_preview: str = ""
    result: dict
    tokens: int = 0
