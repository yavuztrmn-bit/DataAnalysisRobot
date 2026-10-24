# -*- mode: python ; coding: utf-8 -*-
"""
Data Analysis Robot — PyInstaller yapılandırması

Derleme:
    pyinstaller DataAnalysisRobot.spec --noconfirm

Çıktı:
    dist/DataAnalysisRobot.exe   (tek dosya)
"""

import os

block_cipher = None

# ── Programla birlikte paketlenecek dosyalar ──────────────────
# (kaynak, hedef_klasör)
# ── Programla birlikte paketlenecek dosyalar ──────────────────
# Klasördeki arayüz dosyaları ve GÖRSELLER otomatik toplanır.
# Yeni bir resim (örn. chatbot ikonu) eklediğinizde .spec dosyasını
# düzenlemenize gerek yoktur — klasöre koymanız yeterlidir.
import glob

datas = []
_eklenen = set()


def _ekle(dosya, hedef="."):
    if dosya in _eklenen:
        return
    if os.path.exists(dosya):
        datas.append((dosya, hedef))
        _eklenen.add(dosya)


# 1) Arayüz ve veri dosyaları
for _f in ("pls-sem.html", "index.html", "pls-sem-v2.html", "ornek_veri.xlsx"):
    _ekle(_f)

# 2) Tüm görseller (chat_float.png, chat_inside.png, logolar, ikonlar...)
for _kalip in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.webp", "*.ico"):
    for _f in glob.glob(_kalip):
        _ekle(_f)

# 3) CSS / JS varsa
for _kalip in ("*.css", "*.js"):
    for _f in glob.glob(_kalip):
        _ekle(_f)

# 4) static/ klasörü varsa olduğu gibi
if os.path.isdir("static"):
    datas.append(("static", "static"))

# 5) assets/ klasörü varsa
if os.path.isdir("assets"):
    datas.append(("assets", "assets"))

# Arayüz hiç yoksa derlemeyi durdur — çalışmayan bir exe üretmeyelim
_arayuz_var = any(f in ("pls-sem.html", "index.html") for f, _ in datas) \
              or os.path.isdir("static")
if not _arayuz_var:
    raise SystemExit("HATA: pls-sem.html bulunamadi. Derleme durduruldu.")

print(f"[spec] Paketlenecek dosya sayisi: {len(datas)}")
for _f, _ in datas:
    print(f"       + {_f}")

# ── Gizli içe aktarmalar ──────────────────────────────────────
# PyInstaller bazı paketleri otomatik bulamaz; elle bildiriyoruz.
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "scipy._lib.array_api_compat.numpy.fft",
    "scipy.special._special_ufuncs",
    "semopy",
    "pandas._libs.tslibs.base",
    "openpyxl",
    "plssem", "fit_indices", "analysis_queue", "cfa_engine", "app_masaustu", "lisans",
    "tkinter", "tkinter.ttk", "tkinter.font",
]

# ── Gereksiz büyük paketleri dışla (dosya boyutunu düşürür) ───
# DİKKAT: tkinter dışlanmamalı — pencereli başlatıcı onu kullanır.
excludes = [
    "matplotlib", "PyQt5", "PySide2", "PySide6",
    "IPython", "jupyter", "notebook", "pytest", "sphinx",
    "setuptools", "pip",
]

a = Analysis(
    ["baslatici.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DataAnalysisRobot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                 # UPX kuruluysa dosyayı küçültür
    upx_exclude=[
        # Bu kütüphaneler sıkıştırılırsa bozulabilir
        "vcruntime140.dll", "python3*.dll",
        "libopenblas*.dll", "*.pyd",
    ],
    runtime_tmpdir=None,
    console=False,            # Konsol YOK — başlatıcı kendi penceresini açar
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="DataAnalysisRobot.ico",
    version="surum_bilgisi.txt",
)
