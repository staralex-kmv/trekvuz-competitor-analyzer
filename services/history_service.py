"""История анализов: JSON-файл + один глобальный экземпляр (синглтон), как в уроке."""
import json
import threading
from datetime import datetime

import config
from models.schemas import HistoryItem


class HistoryService:
    def __init__(self, path=config.HISTORY_FILE, limit=config.MAX_HISTORY):
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()
        self._items: list[HistoryItem] = []
        if self.path.exists():
            self._items = [HistoryItem(**x) for x in json.loads(self.path.read_text(encoding="utf-8"))]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [x.model_dump(mode="json") for x in self._items]
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, kind: str, result: dict, competitor: str = "", input_preview: str = "", tokens: int = 0) -> HistoryItem:
        with self._lock:
            item = HistoryItem(
                id=(self._items[-1].id + 1) if self._items else 1,
                created_at=datetime.now(),
                kind=kind,
                competitor=competitor,
                input_preview=input_preview[:200],
                result=result,
                tokens=tokens,
            )
            self._items = (self._items + [item])[-self.limit:]
            self._save()
            return item

    def all(self) -> list[HistoryItem]:
        return list(reversed(self._items))

    def clear(self):
        with self._lock:
            self._items = []
            self._save()


history = HistoryService()
