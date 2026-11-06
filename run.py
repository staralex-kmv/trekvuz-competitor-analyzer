"""Запуск сервера разработки: python run.py  (или: uvicorn run:app --reload)."""
import uvicorn

import config
from main import app  # noqa: F401 — нужен для `uvicorn run:app`

if __name__ == "__main__":
    print(f"Монитор конкурентов: http://{config.HOST}:{config.PORT}  (документация API — /docs)")
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
