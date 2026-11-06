"""Сборка desktop-приложения в один исполняемый файл через PyInstaller.

  python build.py            → dist/competition_monitor.exe на Windows (на macOS — dist/competition_monitor)
PyInstaller не кросс-компилирует: .exe собирается только на Windows. Без Windows-машины — GitHub Actions
(.github/workflows/build-exe.yml собирает .exe на windows-latest и прикладывает его к запуску).
Ключ в сборку НЕ попадает: положите .env рядом с исполняемым файлом.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "competition_monitor"
SEP = os.pathsep  # в --add-data разделитель «;» на Windows и «:» на macOS/Linux


def main():
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "desktop" / "app.py"),
        "--name", NAME, "--onefile", "--windowed", "--noconfirm",
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'certs'}{SEP}certs",
        # Selenium ≥ 4.4x импортирует драйверы лениво — PyInstaller их не видит; плюс бинарник Selenium Manager
        "--collect-all", "selenium",
        # FastAPI/uvicorn desktop-версии не нужны — не тащим их в exe
        "--exclude-module", "fastapi", "--exclude-module", "uvicorn", "--exclude-module", "starlette",
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = ROOT / "dist" / (NAME + (".exe" if sys.platform == "win32" else ""))
    print(f"\nГотово: {exe}  ({exe.stat().st_size / 1e6:.1f} МБ)")
    print("Положите рядом .env с GIGACHAT_AUTH_KEY=... и запустите.")


if __name__ == "__main__":
    main()
