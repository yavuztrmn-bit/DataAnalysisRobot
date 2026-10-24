"""
analysis_queue.py — Analiz kuyruğu ve eşzamanlılık koruması
============================================================

NEDEN GEREKLİ
-------------
PLS-SEM analizi CPU-yoğun bir iştir. FastAPI, senkron (`def`) uç noktaları bir
iş parçacığı havuzunda çalıştırır; yani aynı anda gelen 3 istek 3 ayrı çekirdek
talep eder. Paylaşımlı sunucularda CPU kotası genelde tek çekirdek üzerinden
ölçüldüğü için bu durumda isteklerin BİRİ DEĞİL, HEPSİ birden başarısız olur.

Bu modül, aynı anda çalışan analiz sayısını sınırlar. Sırası gelmeyen istek
hata almaz; sessizce bekler ve sırası gelince çalışır. Kullanıcı yalnızca biraz
daha uzun bir "Lütfen bekleyin" ekranı görür.

NOT — neden asyncio değil threading?
------------------------------------
asyncio.Semaphore, ilk kullanıldığı olay döngüsüne (event loop) bağlanır ve
farklı bir döngüden çağrıldığında "bound to a different event loop" hatası
verir. Sunucu yapılandırmasına göre bu gerçekleşebildiği için burada
threading.Semaphore kullanılır: olay döngüsünden bağımsızdır ve iş zaten
iş parçacığı havuzunda çalıştığı için doğal eşleşmedir.

KULLANIM (app.py içinde)
------------------------
    from analysis_queue import run_queued, queue_status

    def _analyze_sync(req):
        ...  # ağır iş

    @app.post("/analyze")
    async def run(req: AnalyzeRequest):
        return await run_queued(_analyze_sync, req)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

# ══════════════════════════════════════════════════════════════
#  AYARLAR — sunucu kapasitenize göre değiştirin
# ══════════════════════════════════════════════════════════════

# Aynı anda çalışacak analiz sayısı.
#   Paylaşımlı hosting / tek çekirdek kotası -> 1
#   2 çekirdek                               -> 2
#   VPS (4+ çekirdek)                        -> çekirdek sayısı - 1
#
# UYARI: Sunucu BİRDEN FAZLA WORKER ile çalışıyorsa (gunicorn -w 4 gibi) bu
# sınır her worker için ayrı geçerlidir; toplam eşzamanlılık
# worker_sayisi x MAX_CONCURRENT olur. Tek worker önerilir.
MAX_CONCURRENT = int(os.environ.get("PLSSEM_MAX_CONCURRENT", "1"))

# Sırada en fazla kaç istek bekleyebilir. Aşılırsa kullanıcıya anlaşılır bir
# "sistem yoğun" mesajı döner. Sonsuz kuyruk herkesin zaman aşımına
# uğramasına yol açar.
MAX_QUEUE = int(os.environ.get("PLSSEM_MAX_QUEUE", "12"))

# Bir istek sırada en fazla kaç saniye bekler. Arayüzün kendi zaman aşımından
# (90 sn) KISA olmalı ki kullanıcı belirsiz bir ağ hatası yerine açıklayıcı
# bir mesaj alsın.
MAX_WAIT_SECONDS = float(os.environ.get("PLSSEM_MAX_WAIT", "70"))

# ══════════════════════════════════════════════════════════════

_sem = threading.Semaphore(MAX_CONCURRENT)
_lock = threading.Lock()

_waiting = 0     # sırada bekleyen
_running = 0     # o an çalışan

STATS = {
    "total": 0,
    "rejected": 0,        # kuyruk dolu
    "timeout": 0,         # sırada beklerken zaman aşımı
    "completed": 0,
    "failed": 0,          # analizin kendisi hata verdi
    "max_wait_seen": 0.0,
    "max_queue_seen": 0,
}

_BUSY_MSG = ("Sistem şu anda yoğun. Lütfen bir dakika sonra tekrar deneyin. "
             "(Analizler sunucuyu korumak için sırayla çalıştırılmaktadır.)")
_WAIT_MSG = ("Sunucu yoğunluğu nedeniyle analiz sıraya alınamadı. "
             "Lütfen birkaç dakika sonra tekrar deneyin.")


def _guarded(fn: Callable[..., Any], args, kwargs):
    """
    İş parçacığı havuzunda çalışır. Semaforu burada alır; böylece bekleme
    olay döngüsünü değil, havuz iş parçacığını meşgul eder.
    Döner: (sonuc, sirada_beklenen_saniye)
    """
    global _waiting, _running

    with _lock:
        if _waiting >= MAX_QUEUE:
            STATS["rejected"] += 1
            raise HTTPException(status_code=503, detail=_BUSY_MSG)
        _waiting += 1
        if _waiting > STATS["max_queue_seen"]:
            STATS["max_queue_seen"] = _waiting

    t0 = time.time()
    try:
        got = _sem.acquire(timeout=MAX_WAIT_SECONDS)
    finally:
        with _lock:
            _waiting -= 1

    if not got:
        with _lock:
            STATS["timeout"] += 1
        raise HTTPException(status_code=503, detail=_WAIT_MSG)

    waited = time.time() - t0
    with _lock:
        _running += 1
        if waited > STATS["max_wait_seen"]:
            STATS["max_wait_seen"] = round(waited, 1)

    try:
        result = fn(*args, **kwargs)
        with _lock:
            STATS["completed"] += 1
        return result, waited
    except Exception:
        with _lock:
            STATS["failed"] += 1
        raise
    finally:
        with _lock:
            _running -= 1
        _sem.release()


async def run_queued(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """
    `fn` işini kuyruğa alarak çalıştırır.

    - Sıra boşsa hemen çalışır, hiç gecikme olmaz.
    - Meşgulse sırada bekler; kullanıcı yalnızca daha uzun bekler.
    - Kuyruk dolarsa 503 ve anlaşılır bir mesaj döner.
    """
    with _lock:
        STATS["total"] += 1

    result, waited = await run_in_threadpool(_guarded, fn, args, kwargs)

    # Sırada beklendiyse sonuca bilgi notu ekle (arayüz kullanmak zorunda değil)
    if isinstance(result, dict) and waited > 0.5:
        meta = result.get("meta")
        if isinstance(meta, dict):
            meta["queue_wait_seconds"] = round(waited, 1)
        elif meta is None:
            result["meta"] = {"queue_wait_seconds": round(waited, 1)}

    return result


def queue_status() -> dict:
    """Anlık durum — izleme uç noktası için."""
    with _lock:
        return {
            "max_concurrent": MAX_CONCURRENT,
            "max_queue": MAX_QUEUE,
            "max_wait_seconds": MAX_WAIT_SECONDS,
            "running": _running,
            "waiting": _waiting,
            "stats": dict(STATS),
        }
