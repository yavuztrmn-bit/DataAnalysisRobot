"""
lisans.py — Masaüstü sürüm lisans yönetimi
===========================================

Nasıl çalışır
-------------
1. Program KEY OLMADAN açılır ve temel analizler çalışır.
2. Kullanıcı premium bir özelliğe tıkladığında (CFA, Bootstrap 5000,
   Word raporu) key sorulur.
3. Key girildiğinde plssem.com'a bir kez sorulur.
4. Sonuç bu bilgisayara kaydedilir; sonraki açılışlarda internet GEREKMEZ.

Sunucu yükü
-----------
Web sürümünde her oturumda doğrulama yapılır. Masaüstünde yalnızca
BİR KEZ. 200 kullanıcı = toplam 200 istek. Analiz yükü ise hiç
sunucuya gelmez, kullanıcının kendi bilgisayarında çalışır.

Sunucuya ulaşılamazsa
---------------------
• Daha önce aktive edilmişse: sorunsuz çalışmaya devam eder.
• Hiç aktive edilmemişse: kullanıcıya anlaşılır bir mesaj döner.

Güvenlik notu
-------------
PyInstaller kodu ŞİFRELEMEZ, paketler. Bilen biri lisans kontrolünü
devre dışı bırakabilir. Buradaki önlemler (makine bağlama, imzalı
önbellek) dürüst kullanımı yönlendirmek içindir; kararlı birini
durdurmaz. Bu, tüm Python masaüstü uygulamaları için geçerlidir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════════
#  AYARLAR
# ══════════════════════════════════════════════════════════════
SUNUCU = os.environ.get("PLSSEM_SERVER", "https://plssem.com")
ZAMAN_ASIMI = 12          # saniye — sunucu yanıtı için

# Önbellek imzası. Kullanıcının dosyayı elle düzenlemesini zorlaştırır.
# Yayın öncesi DEĞİŞTİRİN ve gizli tutun.
_GIZLI = b"DAR-2026-plssem-desktop-v1-change-me"

# Sunucuya hiç ulaşılamazsa ve daha önce aktive edilmemişse
# kaç gün deneme modunda çalışsın (0 = kapalı)
DENEME_GUN = 0


# ══════════════════════════════════════════════════════════════
#  Makine kimliği
# ══════════════════════════════════════════════════════════════
def _makine_ham() -> str:
    """Bu bilgisayarı tanımlayan, mümkün olduğunca kararlı bir dize."""
    parcalar = [platform.node(), platform.machine(), platform.system()]

    # Windows: MachineGuid — donanım değişse bile sabit kalır
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography",
                 "/v", "MachineGuid"],
                stderr=subprocess.DEVNULL, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).decode("utf-8", "ignore")
            for satir in out.splitlines():
                if "MachineGuid" in satir:
                    parcalar.append(satir.split()[-1])
                    break
        except Exception:
            pass

    try:
        import uuid
        parcalar.append(str(uuid.getnode()))       # MAC adresi
    except Exception:
        pass

    return "|".join(p for p in parcalar if p)


def makine_kimligi() -> str:
    """Kısa, gösterilebilir makine kimliği (parmak izi)."""
    return hashlib.sha256(_makine_ham().encode()).hexdigest()[:32]


# ══════════════════════════════════════════════════════════════
#  Yerel önbellek
# ══════════════════════════════════════════════════════════════
def _onbellek_yolu() -> str:
    """
    Lisans dosyası kullanıcı klasöründe tutulur — .exe'nin yanında DEĞİL.
    Tek dosyalı derlemede program her açılışta geçici klasöre açıldığı
    için oraya yazılan hiçbir şey kalıcı olmaz.
    """
    if platform.system() == "Windows":
        kok = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif platform.system() == "Darwin":
        kok = os.path.expanduser("~/Library/Application Support")
    else:
        kok = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    klasor = os.path.join(kok, "DataAnalysisRobot")
    try:
        os.makedirs(klasor, exist_ok=True)
    except Exception:
        klasor = os.path.expanduser("~")
    return os.path.join(klasor, "lisans.json")


def _imzala(veri: dict) -> str:
    ham = json.dumps(veri, sort_keys=True, ensure_ascii=False).encode()
    return hmac.new(_GIZLI, ham, hashlib.sha256).hexdigest()


def _onbellek_oku() -> dict | None:
    try:
        with open(_onbellek_yolu(), encoding="utf-8") as f:
            paket = json.load(f)
        veri = paket.get("veri")
        imza = paket.get("imza")
        if not veri or not imza:
            return None
        if not hmac.compare_digest(_imzala(veri), imza):
            return None                                  # elle değiştirilmiş
        if veri.get("makine") != makine_kimligi():
            return None                                  # başka bilgisayar
        return veri
    except Exception:
        return None


def _onbellek_yaz(veri: dict) -> bool:
    try:
        veri = dict(veri)
        veri["makine"] = makine_kimligi()
        with open(_onbellek_yolu(), "w", encoding="utf-8") as f:
            json.dump({"veri": veri, "imza": _imzala(veri)}, f,
                      ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def onbellek_sil() -> bool:
    """Lisansı bu bilgisayardan kaldırır (kullanıcı 'Çıkış' derse)."""
    try:
        p = _onbellek_yolu()
        if os.path.exists(p):
            os.remove(p)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
#  Süre hesabı
# ══════════════════════════════════════════════════════════════
def _kalan(expires_at) -> dict:
    if not expires_at:
        return {"expires_at": None, "days_left": None, "unlimited": True}
    try:
        son = datetime.fromisoformat(str(expires_at).replace("Z", ""))
    except Exception:
        return {"expires_at": expires_at, "days_left": None, "unlimited": False}
    kalan = (son - datetime.now()).days
    return {"expires_at": str(expires_at), "days_left": kalan,
            "unlimited": False, "expired": kalan < 0}


# ══════════════════════════════════════════════════════════════
#  Sunucu doğrulaması
# ══════════════════════════════════════════════════════════════
def _sunucuya_sor(key: str) -> dict:
    """
    plssem.com'a bir kez sorar. Ağ hatası ile 'geçersiz key' ayrı ayrı
    raporlanır — kullanıcı doğru mesajı görsün.
    """
    gonder = json.dumps({
        "key": key,
        "fingerprint": makine_kimligi(),
    }).encode()

    istek = urllib.request.Request(
        f"{SUNUCU}/api/verify-key",
        data=gonder,
        headers={"Content-Type": "application/json",
                 "User-Agent": "DataAnalysisRobot-Desktop/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            return {"ag": True, "sonuc": json.loads(yanit.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        try:
            govde = json.loads(e.read().decode("utf-8"))
        except Exception:
            govde = {"valid": False, "error": f"Sunucu hatası ({e.code})"}
        return {"ag": True, "sonuc": govde}
    except Exception as e:
        return {"ag": False, "hata": str(e)}


# ══════════════════════════════════════════════════════════════
#  Dışa açık işlevler
# ══════════════════════════════════════════════════════════════
def durum() -> dict:
    """Kayıtlı lisans var mı? Program açılışında ve premium kontrolünde kullanılır."""
    veri = _onbellek_oku()
    if not veri:
        return {"valid": False, "activated": False,
                "message": "Premium özellikler için erişim key'i gerekir."}

    k = _kalan(veri.get("expires_at"))
    if k.get("expired"):
        return {"valid": False, "activated": True, "expired": True,
                "key": veri.get("key"),
                "message": "Erişim key'inizin süresi dolmuş."}

    return {
        "valid": True, "ok": True, "activated": True,
        "key": veri.get("key"),
        "label": veri.get("label", ""),
        "is_admin": veri.get("is_admin", False),
        "package": veri.get("package", "premium"),
        "activated_at": veri.get("activated_at"),
        "source": "cache",
        **k,
    }


def dogrula(key: str) -> dict:
    """
    Key doğrulama. Önce yerel önbelleğe, sonra sunucuya bakar.
    Başarılıysa sonucu bu bilgisayara kaydeder.
    """
    key = (key or "").strip().upper()
    if not key:
        return {"valid": False, "error": "Lütfen erişim key'inizi girin."}

    # Aynı key zaten kayıtlıysa sunucuya hiç gitme
    veri = _onbellek_oku()
    if veri and veri.get("key") == key:
        d = durum()
        if d.get("valid"):
            return d

    cevap = _sunucuya_sor(key)

    # ── Ağ yok ──
    if not cevap.get("ag"):
        if veri:      # daha önce aktive edilmiş -> çalışmaya devam
            d = durum()
            if d.get("valid"):
                d["message"] = "Çevrimdışı mod — kayıtlı lisans kullanılıyor."
                return d
        return {"valid": False, "offline": True,
                "error": ("İnternet bağlantısı kurulamadı. Key'i ilk kez "
                          "etkinleştirmek için internet gerekir. Bağlantınızı "
                          "kontrol edip tekrar deneyin.")}

    sonuc = cevap.get("sonuc") or {}
    if not (sonuc.get("valid") or sonuc.get("ok")):
        return {"valid": False,
                "error": sonuc.get("error") or sonuc.get("detail")
                         or "Key doğrulanamadı."}

    # ── Başarılı: kaydet ──
    kayit = {
        "key": key,
        "label": sonuc.get("label", ""),
        "is_admin": bool(sonuc.get("is_admin", False)),
        "package": sonuc.get("package", "premium"),
        "activated_at": sonuc.get("activated_at") or datetime.now().isoformat(),
        "expires_at": sonuc.get("expires_at"),
        "kayit_zamani": datetime.now().isoformat(),
    }
    _onbellek_yaz(kayit)

    d = durum()
    d["source"] = "server"
    d["message"] = "Premium erişim etkinleştirildi."
    return d
