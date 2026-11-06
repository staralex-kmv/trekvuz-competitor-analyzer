"""Desktop-версия «Монитора конкурентов» на PyQt6: те же вкладки, что на сайте, но без сервера —
вызывает сервисы (GigaChat, Selenium, история) напрямую. Тяжёлые вызовы идут в фоновом потоке, окно не зависает.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # корень проекта: config, models, services

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

import config
from services.gigachat_service import get_service
from services.history_service import history
from services.pipeline import run_parse  # тот же конвейер, что у эндпоинта /parse/demo

LABELS = {
    "strengths": "Сильные стороны", "weaknesses": "Слабые стороны", "unique_offers": "Уникальные предложения",
    "recommendations": "Рекомендации для Трек ВУЗ", "marketing_insights": "Маркетинговые инсайты",
    "trust_signals": "Сигналы доверия",
}
SCORES = {
    "data_trust_score": "доверие к данным", "threat_level": "угроза для нас", "visual_style_score": "визуальный стиль",
    "design_score": "дизайн/UX", "trust_score": "доверие (визуально)",
}


def to_html(a: dict, title: str) -> str:
    if not a:
        return ""
    scores = " · ".join(f"<b>{a[k]}</b>/10 {v}" for k, v in SCORES.items() if k in a)
    text = "".join(f"<p>{a[k]}</p>" for k in ("summary", "description", "visual_style_analysis", "data_trust_reason") if a.get(k))
    lists = "".join(f"<h4>{v}</h4><ul>{''.join(f'<li>{x}</li>' for x in a[k])}</ul>" for k, v in LABELS.items() if a.get(k))
    return f"<h3>{title}</h3><p>{scores}</p>{text}{lists}<hr>"


class Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Монитор конкурентов — Трек ВУЗ")
        self.resize(1000, 760)
        self.worker = None

        self.tabs = QTabWidget()
        self.tabs.addTab(self._text_tab(), "Текст")
        self.tabs.addTab(self._file_tab("image"), "Изображение")
        self.tabs.addTab(self._file_tab("pdf"), "PDF")
        self.tabs.addTab(self._parse_tab(), "Парсинг сайта")
        self.tabs.addTab(self._history_tab(), "История")

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # бесконечная полоса, пока ждём модель
        self.progress.hide()
        self.status = QLabel("")
        self.output = QTextBrowser()
        self.output.setOpenExternalLinks(True)
        self.shot = QLabel()

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addWidget(self.tabs)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.shot)
        lay.addWidget(self.output, 1)
        self.setCentralWidget(root)

    # --- вкладки ---
    def _text_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.text_comp = QLineEdit(placeholderText="Конкурент")
        self.text_in = QTextEdit(placeholderText="Текст конкурента: описание продукта, тарифы, лендинг")
        btn = QPushButton("Проанализировать")
        btn.clicked.connect(self.on_text)
        for x in (self.text_comp, self.text_in, btn):
            lay.addWidget(x)
        return w

    def _file_tab(self, kind):
        w = QWidget()
        lay = QVBoxLayout(w)
        comp = QLineEdit(placeholderText="Конкурент")
        path = QLineEdit(placeholderText="Файл .png/.jpg" if kind == "image" else "Файл .pdf")
        pick = QPushButton("Выбрать файл…")
        flt = "Изображения (*.png *.jpg *.jpeg)" if kind == "image" else "PDF (*.pdf)"
        pick.clicked.connect(lambda: path.setText(QFileDialog.getOpenFileName(self, "Файл", str(config.DATA_DIR), flt)[0]))
        go = QPushButton("Проанализировать")
        go.clicked.connect(lambda: self.on_file(kind, path.text(), comp.text()))
        row = QHBoxLayout()
        row.addWidget(path)
        row.addWidget(pick)
        lay.addWidget(comp)
        lay.addLayout(row)
        lay.addWidget(go)
        lay.addStretch()
        return w

    def _parse_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.parse_combo = QComboBox()
        self.parse_combo.addItem("Все конкуренты из config.py", None)
        for name, url in config.COMPETITOR_URLS.items():
            self.parse_combo.addItem(f"{name} — {url}", (name, url))
        self.parse_url = QLineEdit(placeholderText="…или свой адрес https://")
        go = QPushButton("Открыть в Chrome и проанализировать")
        go.clicked.connect(self.on_parse)
        for x in (self.parse_combo, self.parse_url, go):
            lay.addWidget(x)
        lay.addStretch()
        return w

    def _history_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.hist_list = QListWidget()
        self.hist_list.itemClicked.connect(self.on_hist_item)
        row = QHBoxLayout()
        refresh, clear = QPushButton("Обновить"), QPushButton("Очистить")
        refresh.clicked.connect(self.load_history)
        clear.clicked.connect(self.on_clear)
        row.addWidget(refresh)
        row.addWidget(clear)
        lay.addLayout(row)
        lay.addWidget(self.hist_list)
        self.tabs_history_items = []
        return w

    # --- запуск в фоне ---
    def run_bg(self, label, fn, show):
        if self.worker and self.worker.isRunning():
            return
        self.output.clear()
        self.shot.clear()
        self.status.setText(label)
        self.progress.show()
        self.worker = Worker(fn)
        self.worker.done.connect(lambda r: (self.progress.hide(), self.status.setText("Готово"), show(r)))
        self.worker.failed.connect(lambda e: (self.progress.hide(), self.status.setText(""), QMessageBox.warning(self, "Ошибка", e)))
        self.worker.start()

    def on_text(self):
        text, comp = self.text_in.toPlainText(), self.text_comp.text()
        if len(text) < 20:
            QMessageBox.information(self, "Мало текста", "Вставьте хотя бы пару предложений")
            return

        def job():
            a, tokens = get_service().analyze_text(text)
            history.add("text", a.model_dump(), comp, text, tokens)
            return a.model_dump(), tokens
        self.run_bg("Анализ текста…", job, lambda r: self.output.setHtml(to_html(r[0], f"{comp or 'Текст'} · {r[1]} ток.")))

    def on_file(self, kind, path, comp):
        p = Path(path)
        if not p.is_file():
            QMessageBox.information(self, "Нет файла", "Выберите файл")
            return

        def job():
            svc = get_service()
            if kind == "image":
                a, tokens = svc.analyze_image(p)
            else:
                a, tokens, _ = svc.analyze_pdf(p)
            history.add(kind, a.model_dump(), comp, p.name, tokens)
            return a.model_dump(), tokens

        def show(r):
            self.output.setHtml(to_html(r[0], f"{comp or p.name} · {r[1]} ток."))
            if kind == "image":
                self.shot.setPixmap(QPixmap(str(p)).scaledToWidth(480))
        self.run_bg("Анализ файла…", job, show)

    def on_parse(self):
        custom = self.parse_url.text().strip()
        if custom:
            targets = {custom: custom}
        elif self.parse_combo.currentData():
            name, url = self.parse_combo.currentData()
            targets = {name: url}
        else:
            targets = config.COMPETITOR_URLS

        def job():
            return [run_parse(n, u).model_dump() for n, u in targets.items()]
        self.run_bg("Chrome открывает сайт(ы), GigaChat анализирует… (до минуты на сайт)", job, self.show_parse)

    def show_parse(self, results):
        html = ""
        for p in results:
            html += f"<h2>{p['competitor']} — {p['title']}</h2><p><a href='{p['url']}'>{p['url']}</a> {p['error']}</p>"
            html += to_html(p.get("text_analysis"), "Анализ текста сайта") + to_html(p.get("image_analysis"), "Анализ скриншота")
        self.output.setHtml(html)
        if results and results[-1].get("screenshot"):
            self.shot.setPixmap(QPixmap(str(config.BASE_DIR / results[-1]["screenshot"])).scaledToWidth(480))

    def load_history(self):
        self.hist_list.clear()
        self.tabs_history_items = history.all()
        for h in self.tabs_history_items:
            self.hist_list.addItem(f"[{h.kind}] {h.competitor or '—'} · {h.created_at:%d.%m %H:%M} · {h.tokens} ток.")

    def on_hist_item(self, item):
        h = self.tabs_history_items[self.hist_list.row(item)]
        if h.kind == "parse":
            self.show_parse([h.result])
        else:
            self.output.setHtml(to_html(h.result, h.competitor or h.kind))

    def on_clear(self):
        if QMessageBox.question(self, "История", "Очистить историю?") == QMessageBox.StandardButton.Yes:
            history.clear()
            self.load_history()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if "--smoke" in sys.argv:  # проверка сборки: окно создалось, сертификат упакован, GigaChat отвечает — выходим
        a, tokens = get_service().analyze_text(
            "Сервис подбора вузов: каталог 1 000 вузов, калькулятор баллов ЕГЭ, всё бесплатно. Источники данных не указаны.")
        print(json.dumps({"ok": True, "tabs": win.tabs.count(), "data_trust_score": a.data_trust_score,
                          "tokens": tokens}, ensure_ascii=False))
        if "--parse" in sys.argv:  # + Selenium из сборки: открыть одного конкурента
            name, url = next(iter(config.COMPETITOR_URLS.items()))
            r = run_parse(name, url)
            print(json.dumps({"parse": name, "chars": r.text_chars, "screenshot": r.screenshot,
                              "design_score": r.image_analysis.design_score if r.image_analysis else None,
                              "error": r.error}, ensure_ascii=False))
        return
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
