"""
app_masaustu.py — Data Analysis Robot masaüstü sürümü
======================================================

Sunucudaki app.py'nin SADELEŞTİRİLMİŞ hâlidir. Yalnızca PLS-SEM ve CFA
içerir; platformun diğer modülleri (göz izleme, anket, bibliyometri,
AI sohbet vb.) masaüstü sürümde YER ALMAZ çünkü bunlar sunucu tarafı
altyapı ve API anahtarları gerektirir.

Sunucu sürümünden farkları
--------------------------
  • 12 route modülüne bağımlılık yok  -> tek dosyayla çalışır
  • Lisans/key doğrulama yok          -> tüm özellikler açık
  • static/ klasör yapısı zorunlu değil
  • Yalnızca 127.0.0.1'e bağlanır     -> dışarıya kapalı

Analiz motoru (plssem.py, fit_indices.py, cfa_engine.py) sunucudakiyle
BİREBİR AYNIDIR. Sonuçlar farklı çıkmaz.
"""

import os
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from plssem import analyze
from analysis_queue import run_queued, queue_status

try:
    from cfa_engine import run_cfa as run_cfa_engine
    _HAS_CFA = True
except Exception:
    _HAS_CFA = False

APP_NAME = "Data Analysis Robot"
VERSION = "1.0.0"
ROOT = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
#  MODELLER — sunucudakiyle aynı (arayüz aynı JSON'u gönderir)
# ══════════════════════════════════════════════════════════════
class Construct(BaseModel):
    name: str
    items: List[str]


class Hypothesis(BaseModel):
    from_: str = Field(alias="from")
    to: str
    number: Optional[int] = None


class ControlVar(BaseModel):
    name: str
    column: str


class Interaction(BaseModel):
    name: str
    a: str
    b: str
    standardize: bool = True


class AnalyzeRequest(BaseModel):
    data: List[Dict[str, Any]]
    constructs: List[Construct]
    hypotheses: List[Hypothesis]
    controls: List[ControlVar] = []
    interactions: List[Interaction] = []
    bootstrap_samples: int = 500


class CFARequest(BaseModel):
    data: List[Dict[str, Any]]
    constructs: List[Construct]


class KeyRequest(BaseModel):
    key: Optional[str] = None
    fingerprint: Optional[str] = None


# ══════════════════════════════════════════════════════════════
def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Metin gelen sayısal sütunları sayıya çevirir (virgüllü ondalık dahil)."""
    for c in df.columns:
        if df[c].dtype == object:
            s = df[c].astype(str).str.strip().str.replace(",", ".", regex=False)
            conv = pd.to_numeric(s, errors="coerce")
            # Çoğunluk sayıya dönüştüyse sayısal kabul et
            if conv.notna().sum() >= max(1, int(0.8 * len(conv))):
                df[c] = conv
    return df


# ══════════════════════════════════════════════════════════════
#  ANALİZ UÇ NOKTALARI
# ══════════════════════════════════════════════════════════════
def _analyze_sync(req: AnalyzeRequest):
    df = _coerce_numeric(pd.DataFrame(req.data))
    constructs   = [{"name": c.name, "items": c.items} for c in req.constructs]
    hypotheses   = [{"from": h.from_, "to": h.to, "number": h.number} for h in req.hypotheses]
    controls     = [{"name": c.name, "column": c.column} for c in req.controls]
    interactions = [{"name": i.name, "a": i.a, "b": i.b, "standardize": i.standardize}
                    for i in req.interactions]
    B = int(req.bootstrap_samples or 500)
    B = max(200, min(B, 20000))
    return analyze(df, constructs, hypotheses, controls, interactions, bootstrap_samples=B)


@app.post("/analyze")
async def run(req: AnalyzeRequest):
    return await run_queued(_analyze_sync, req)


def _cfa_sync(req: CFARequest):
    if not _HAS_CFA:
        raise HTTPException(status_code=501,
                            detail="CFA modülü bu kurulumda mevcut değil (cfa_engine.py eksik).")
    df = _coerce_numeric(pd.DataFrame(req.data))
    constructs = [{"name": c.name, "items": c.items} for c in req.constructs]
    return run_cfa_engine(df, constructs)


@app.post("/cfa/analyze")
async def run_cfa_endpoint(req: CFARequest):
    return await run_queued(_cfa_sync, req)


# ══════════════════════════════════════════════════════════════
#  LİSANS
#  Temel analizler KEY OLMADAN çalışır. Key yalnızca premium
#  özellikler için gerekir (CFA, Bootstrap 5000, Word raporu).
#
#  Akış: kullanıcı key girer -> plssem.com'a BİR KEZ sorulur ->
#  sonuç bu bilgisayara kaydedilir -> sonraki açılışlarda internet
#  gerekmez. Ayrıntı: lisans.py
# ══════════════════════════════════════════════════════════════
try:
    import lisans
    _HAS_LISANS = True
except Exception:
    _HAS_LISANS = False


def _lisans_yok():
    return {"valid": False, "activated": False,
            "error": "Lisans modülü yüklenemedi."}


@app.post("/api/verify-key")
def verify_key(req: KeyRequest = None):
    """Key doğrula ve etkinleştir."""
    if not _HAS_LISANS:
        return _lisans_yok()
    if req is None or not (req.key or "").strip():
        return {"valid": False, "error": "Lütfen erişim key'inizi girin."}
    return lisans.dogrula(req.key)


@app.post("/api/key-status")
def key_status(req: KeyRequest = None):
    """Kayıtlı lisans durumunu sorgular; sunucuya gitmez."""
    if not _HAS_LISANS:
        return _lisans_yok()
    return lisans.durum()


@app.get("/api/key-status")
def key_status_get():
    if not _HAS_LISANS:
        return _lisans_yok()
    return lisans.durum()


@app.post("/api/license-remove")
def license_remove():
    """Lisansı bu bilgisayardan kaldırır."""
    if not _HAS_LISANS:
        return _lisans_yok()
    ok = lisans.onbellek_sil()
    return {"ok": ok, "message": "Lisans bu bilgisayardan kaldırıldı." if ok
                                 else "Lisans kaldırılamadı."}


@app.get("/api/machine-id")
def machine_id():
    """Destek talebi için makine kimliği."""
    if not _HAS_LISANS:
        return _lisans_yok()
    return {"machine_id": lisans.makine_kimligi()}


# ══════════════════════════════════════════════════════════════
#  DURUM / SAĞLIK
# ══════════════════════════════════════════════════════════════
@app.get("/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": VERSION, "mode": "desktop"}


@app.get("/api/queue-status")
def api_queue_status():
    return queue_status()


@app.get("/api/info")
def api_info():
    return {
        "app": APP_NAME,
        "version": VERSION,
        "mode": "desktop",
        "cores": os.cpu_count(),
        "threads": os.environ.get("OMP_NUM_THREADS"),
        "cfa": _HAS_CFA,
        "license": (lisans.durum() if _HAS_LISANS else _lisans_yok()),
    }


# ══════════════════════════════════════════════════════════════
#  ÖRNEK VERİ  (varsa)
# ══════════════════════════════════════════════════════════════
@app.get("/ornek_veri.xlsx")
def ornek_veri():
    p = os.path.join(ROOT, "ornek_veri.xlsx")
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Örnek veri dosyası bulunamadı.")
    return FileResponse(p)


# ══════════════════════════════════════════════════════════════
#  ARAYÜZ
#  Sunucudaki gibi static/ klasörü ARAMAZ; dosyalar programın
#  bulunduğu klasörde olabilir.
# ══════════════════════════════════════════════════════════════
def _find_dir() -> str:
    for d in (os.path.join(ROOT, "static"), ROOT):
        if os.path.exists(os.path.join(d, "pls-sem.html")):
            return d
    return ROOT


WEB_DIR = _find_dir()


@app.get("/", response_class=HTMLResponse)
def index():
    p = os.path.join(WEB_DIR, "pls-sem.html")
    if os.path.exists(p):
        return FileResponse(p)
    return HTMLResponse(
        f"<h2>{APP_NAME}</h2><p>pls-sem.html bulunamadı.</p>"
        f"<p>Aranan klasör: {WEB_DIR}</p>", status_code=404)


@app.get("/pls-sem-v2")
def v2_page():
    for c in (os.path.join(WEB_DIR, "pls-sem-v2.html"),
              os.path.join(WEB_DIR, "pls-sem-v2", "index.html")):
        if os.path.exists(c):
            return FileResponse(c)
    raise HTTPException(status_code=404, detail="V2 arayüzü bu kurulumda yok.")


# Diğer tüm statik dosyalar (html, css, js, resim)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
