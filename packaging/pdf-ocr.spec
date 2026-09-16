# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir bundle for the portable, offline PDF OCR application.

Build with:  pyinstaller packaging/pdf-ocr.spec --noconfirm

The result is dist/pdf-ocr/. Copying that folder together with a models
folder beside the executable is enough to run on a machine with no Python
and no internet connection.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

APP_NAME = "pdf-ocr"
PROJECT_ROOT = Path(SPECPATH).resolve().parent
ICON_FILE = PROJECT_ROOT / "packaging" / "icon.ico"

# Interface assets are read from disk at run time, so they must travel along.
datas = [
    (str(PROJECT_ROOT / "src" / "gui" / "styles" / "dark_theme.qss"), "src/gui/styles"),
    (str(PROJECT_ROOT / "src" / "gui" / "styles" / "light_theme.qss"), "src/gui/styles"),
]
translations = PROJECT_ROOT / "src" / "gui" / "translations"
datas += [(str(path), "src/gui/translations") for path in translations.glob("*.qm")]

# OCR providers are imported lazily by name, so PyInstaller cannot see them.
hiddenimports: list[str] = []
for provider in ("vietocr", "paddleocr", "surya", "transformers", "easyocr", "torch"):
    try:
        hiddenimports += collect_submodules(provider)
    except Exception:  # noqa: BLE001 - an absent provider must not fail the build
        pass

# Qt modules the application never touches only make the bundle larger.
excludes = [
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "matplotlib",
    "tkinter",
]

analysis = Analysis(
    [str(PROJECT_ROOT / "src" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE) if ICON_FILE.is_file() else None,
)

COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
