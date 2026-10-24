"""
Data Analysis Robot — Masaüstü Başlatıcı (pencereli)
=====================================================
Komut ekranı YERİNE düzgün bir pencere gösterir:

  1. Logolu açılış ekranı + ilerleme çubuğu
  2. "İlk açılış 2-4 dakika sürebilir" uyarısı ve saniye sayacı
  3. Hazır olunca tarayıcı açılır, pencere kontrol paneline döner
  4. Pencere kapatılınca sunucu da kapanır

Neden pencere: siyah komut ekranı kullanıcıya "bir şeyler ters gitti"
hissi veriyor. Bu sürümde kullanıcı hiç konsol görmez.
"""

import os
import socket
import sys
import threading
import time
import webbrowser


# ══════════════════════════════════════════════════════════════
#  PENCERELİ MOD DÜZELTMESİ  (console=False)
#  PyInstaller pencereli derlemede sys.stdout ve sys.stderr None olur.
#  uvicorn'un günlük sistemi stdout.isatty() çağırdığı için
#  "AttributeError: 'NoneType' object has no attribute 'isatty'"
#  hatası verir. Sahte bir akış koyarak bunu engelliyoruz.
# ══════════════════════════════════════════════════════════════
class _SessizAkis:
    """Hiçbir yere yazmayan, ama gerçek bir akış gibi davranan nesne."""
    encoding = "utf-8"
    errors = "replace"

    def write(self, *a, **k):
        return 0

    def flush(self, *a, **k):
        pass

    def isatty(self):
        return False

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    def fileno(self):
        raise OSError("akış yok")

    def close(self):
        pass


if sys.stdout is None:
    sys.stdout = _SessizAkis()
if sys.stderr is None:
    sys.stderr = _SessizAkis()
if sys.stdin is None:
    sys.stdin = _SessizAkis()

APP_NAME = "Data Analysis Robot"
APP_SUB = "Free Data Analysis Platform · plssem.com"
VERSION = "1.0.0"

# Sitedeki atıf ifadesiyle aynı
TELIF = "© 2026 plssem.com · All rights reserved · Developed by Dr. Yavuz Toraman"

ATIF_BASLIK = ("The Data Analysis Robot can freely used for academic purposes, "
               "if the source is correctly cited.")
ATIF = ("Toraman, Y. (2026). Data Analysis Robot — PLS-SEM Module (Version 1.0) "
        "[Web application]. https://plssem.com")

# ══════════════════════════════════════════════════════════════
#  ÇOK ÇEKİRDEK — numpy import EDİLMEDEN ÖNCE ayarlanmalı.
#  Sunucu sürümünde bu değer 1'e sabitliydi (CPU kotası koruması);
#  masaüstünde kota yoktur, tüm çekirdekler kullanılır.
# ══════════════════════════════════════════════════════════════
_cores = os.cpu_count() or 1
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = str(_cores)
os.environ.setdefault("PLSSEM_MAX_CONCURRENT", str(_cores))
os.environ.setdefault("PLSSEM_MAX_QUEUE", "8")

# ── Renkler (markayla uyumlu) ─────────────────────────────────
# Açık tema — üst bant ve gövde tek parça görünsün
BG     = "#ffffff"      # gövde
PANEL  = "#ffffff"      # üst bant
KUTU   = "#f1f5f9"      # adres kutusu, düğme zemini
BORDER = "#e2e8f0"      # ince ayırıcılar
TXT    = "#0f172a"      # ana metin
TXT2   = "#5b6b82"      # ikincil metin
TXT3   = "#8b97a8"      # en soluk (İngilizce satırlar)
ACCENT = "#f97316"
OK     = "#15803d"
WARN   = "#b45309"
RED    = "#b91c1c"
UYARI_BG   = "#fffbeb"
UYARI_KENAR= "#f0c674"


def base_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def free_port(start=8756, limit=60):
    for p in range(start, start + limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("Boş port bulunamadı.")


# ══════════════════════════════════════════════════════════════
class Pencere:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        try:
            ico = os.path.join(base_dir(), "DataAnalysisRobot.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

        W, H = 560, 580
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 3}")

        self.port = None
        self.server = None
        self.hazir = False
        self.t0 = time.time()

        self._kur()
        self.root.protocol("WM_DELETE_WINDOW", self.kapat)

    # ── Arayüz ──────────────────────────────────────────────
    def _kur(self):
        tk, ttk = self.tk, self.ttk

        ust = tk.Frame(self.root, bg=PANEL, height=140)
        ust.pack(fill="x")
        ust.pack_propagate(False)

        # Logo: EKRANDA GÖRÜNECEĞİ BOYUTTA hazır dosya kullanılır.
        # tkinter'ın subsample() fonksiyonu pikselleri atlayarak küçültür ve
        # kenarları tırtıklı gösterir; bu yüzden logo_win.png önceden
        # LANCZOS ile 64px olarak üretilmiştir.
        self.logo_img = None
        for ad in ("logo_win.png", "logo_256.png"):
            yol = os.path.join(base_dir(), ad)
            if not os.path.exists(yol):
                continue
            try:
                img = tk.PhotoImage(file=yol)
                if img.width() > 80:                 # yedek dosya: küçültmek gerekir
                    img = img.subsample(max(1, img.width() // 64))
                self.logo_img = img
                tk.Label(ust, image=self.logo_img, bg=PANEL).pack(
                    side="left", padx=(18, 14), pady=34)
                break
            except Exception:
                continue

        bilgi = tk.Frame(ust, bg=PANEL)
        bilgi.pack(side="left", pady=(20, 18))
        tk.Label(bilgi, text=APP_NAME, bg=PANEL, fg=TXT,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(bilgi, text=APP_SUB, bg=PANEL, fg=TXT2,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(bilgi, text=f"Version {VERSION}",
                 bg=PANEL, fg=TXT3, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        tk.Label(bilgi, text=TELIF, bg=PANEL, fg=TXT3,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        self.govde = tk.Frame(self.root, bg=BG)
        self.govde.pack(fill="both", expand=True, padx=24, pady=18)

        self.durum = tk.Label(self.govde, text="Program başlatılıyor  ·  Starting up",
                              bg=BG, fg=TXT, font=("Segoe UI", 12, "bold"))
        self.durum.pack(anchor="w")

        self.alt = tk.Label(self.govde, text="Lütfen bekleyin  ·  Please wait",
                            bg=BG, fg=TXT2, font=("Segoe UI", 10), justify="left")
        self.alt.pack(anchor="w", pady=(3, 12))

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("DAR.Horizontal.TProgressbar", troughcolor=KUTU,
                     background=ACCENT, bordercolor=KUTU,
                     lightcolor=ACCENT, darkcolor=ACCENT)
        self.bar = ttk.Progressbar(self.govde, mode="indeterminate", length=478,
                                   style="DAR.Horizontal.TProgressbar")
        self.bar.pack(pady=(0, 14))
        self.bar.start(14)

        self.uyari = tk.Frame(self.govde, bg=UYARI_BG, highlightthickness=1,
                              highlightbackground=UYARI_KENAR)
        self.uyari.pack(fill="x")
        SARMA = 440      # kutu genişliğine göre satır kaydırma
        tk.Label(self.uyari, text="⏳  İlk açılış 2-4 dakika sürebilir",
                 bg=UYARI_BG, fg=WARN, wraplength=SARMA, justify="left",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 1))
        tk.Label(self.uyari, text="First launch may take 2-4 minutes",
                 bg=UYARI_BG, fg="#a06a1f", wraplength=SARMA, justify="left",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(0, 6))
        tk.Label(self.uyari,
                 text="Program kendini hazırlıyor; bu tek seferliktir. Pencere hareketsiz "
                      "görünse de çalışıyor — lütfen kapatmayın.",
                 bg=UYARI_BG, fg="#6b5a3a", font=("Segoe UI", 9),
                 wraplength=SARMA, justify="left").pack(anchor="w", padx=12, pady=(0, 3))
        tk.Label(self.uyari,
                 text="The app is preparing itself; this happens only once. The window may "
                      "look frozen but it is working — please do not close it.",
                 bg=UYARI_BG, fg="#9a8763", font=("Segoe UI", 9),
                 wraplength=SARMA, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        self.sayac = tk.Label(self.govde, text="", bg=BG, fg=TXT3, font=("Segoe UI", 9))
        self.sayac.pack(anchor="w", pady=(10, 0))
        self._sayac_guncelle()

        self.atif_kutusu = self._atif_yap(self.govde)
        self.atif_kutusu.pack(side="bottom", fill="x", pady=(10, 0))

    def _atif_yap(self, ana):
        """Atıf bilgisi — hem açılış hem hazır ekranında görünür."""
        tk = self.tk
        f = tk.Frame(ana, bg=BG)
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))
        tk.Label(f, text=ATIF_BASLIK, bg=BG, fg=TXT2, font=("Segoe UI", 8),
                 wraplength=478, justify="left").pack(anchor="w")
        tk.Label(f, text=ATIF, bg=BG, fg="#2563a8", font=("Segoe UI", 8),
                 wraplength=478, justify="left").pack(anchor="w", pady=(2, 0))
        return f

    def _sayac_guncelle(self):
        if not self.hazir:
            s = int(time.time() - self.t0)
            dk, sn = divmod(s, 60)
            self.sayac.config(text=(f"Geçen süre · Elapsed: {dk} dk {sn} sn" if dk
                                    else f"Geçen süre · Elapsed: {sn} sn"))
            self.root.after(500, self._sayac_guncelle)

    def bildir(self, baslik, alt=""):
        self.root.after(0, lambda: (self.durum.config(text=baslik),
                                    self.alt.config(text=alt)))

    # ── Hazır ekranı ────────────────────────────────────────
    def hazir_ekrani(self, port):
        tk = self.tk
        self.hazir = True
        self.port = port
        sure = int(time.time() - self.t0)

        self.bar.stop()
        self.bar.pack_forget()
        self.uyari.pack_forget()
        self.sayac.pack_forget()
        self.atif_kutusu.destroy()      # açılıştaki atıf kutusu kaldırılır,
                                        # aşağıda yenisi eklenecek (üst üste binmesin)

        self.durum.config(text="✓   The program was established", fg=OK,
                          font=("Segoe UI", 15, "bold"))
        self.alt.config(text=f"Analiz ekranı tarayıcınızda açıldı  ·  "
                             f"Opened in your browser   ({sure} sn)")

        kutu = tk.Frame(self.govde, bg=KUTU, highlightthickness=1,
                        highlightbackground=BORDER)
        kutu.pack(fill="x", pady=(8, 16))
        tk.Label(kutu, text="ADDRESS", bg=KUTU, fg=TXT2,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(9, 0))
        tk.Label(kutu, text=f"http://127.0.0.1:{port}", bg=KUTU, fg=ACCENT,
                 font=("Consolas", 13, "bold")).pack(anchor="w", padx=12, pady=(0, 9))

        dugmeler = tk.Frame(self.govde, bg=BG)
        dugmeler.pack(fill="x")

        tk.Button(dugmeler, text="Open in your browser", bg=ACCENT, fg="white",
                  font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
                  activebackground="#ea580c", activeforeground="white",
                  bd=0, padx=20, pady=10,
                  command=lambda: webbrowser.open(f"http://127.0.0.1:{port}/")
                  ).pack(side="left")

        tk.Button(dugmeler, text="Quit", bg=KUTU, fg=TXT,
                  font=("Segoe UI", 11), relief="flat", cursor="hand2",
                  activebackground=RED, activeforeground="white",
                  bd=0, padx=20, pady=10, command=self.kapat).pack(side="right")

        tk.Label(self.govde,
                 text="Analiz bu bilgisayarda çalışır; verileriniz dışarı gönderilmez. "
                      "Tarayıcı sekmesini kapatmak programı kapatmaz — bu pencereyi kapatın.",
                 bg=BG, fg=TXT2, font=("Segoe UI", 9), wraplength=478,
                 justify="left").pack(anchor="w", pady=(16, 3))
        tk.Label(self.govde,
                 text="Analyses run on this computer; your data is never sent anywhere. "
                      "Closing the browser tab does not quit the program — close this window.",
                 bg=BG, fg=TXT3, font=("Segoe UI", 9), wraplength=478,
                 justify="left").pack(anchor="w")

        self._atif_yap(self.govde).pack(side="bottom", fill="x", pady=(10, 0))

    def hata_ekrani(self, mesaj):
        tk = self.tk
        self.hazir = True
        try:
            self.bar.stop()
            self.bar.pack_forget()
            self.uyari.pack_forget()
            self.sayac.pack_forget()
            self.atif_kutusu.destroy()
        except Exception:
            pass

        self.durum.config(text="✕   Başlatılamadı  ·  Failed to start", fg=RED,
                          font=("Segoe UI", 15, "bold"))
        self.alt.config(text="Aşağıdaki hata oluştu  ·  The following error occurred:")

        kutu = tk.Text(self.govde, height=8, bg="#fef2f2", fg="#991b1b", relief="flat",
                       font=("Consolas", 8), wrap="word", padx=10, pady=8)
        kutu.insert("1.0", str(mesaj))
        kutu.config(state="disabled")
        kutu.pack(fill="both", expand=True, pady=(6, 12))

        tk.Button(self.govde, text="Kapat  ·  Close", bg=KUTU, fg=TXT, relief="flat",
                  font=("Segoe UI", 10), padx=20, pady=9, bd=0,
                  cursor="hand2", command=self.kapat).pack(side="right")

    def kapat(self):
        try:
            if self.server is not None:
                self.server.should_exit = True
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)


# ══════════════════════════════════════════════════════════════
def sunucuyu_baslat(pencere):
    """Arka planda: motoru yükle, sunucuyu çalıştır."""
    root = base_dir()
    try:
        os.chdir(root)
    except Exception:
        pass
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        pencere.bildir("Dosyalar kontrol ediliyor  ·  Checking files", "")
        varmi = any(os.path.exists(os.path.join(d, f))
                    for d in (root, os.path.join(root, "static"))
                    for f in ("pls-sem.html", "index.html"))
        if not varmi:
            pencere.root.after(0, lambda: pencere.hata_ekrani(
                f"Arayüz dosyası (pls-sem.html) bulunamadı.\n"
                f"Interface file (pls-sem.html) not found.\n\n"
                f"Aranan konum · Searched in:\n{root}"))
            return

        pencere.bildir("Analiz motoru yükleniyor  ·  Loading analysis engine",
                       "En uzun adım  ·  This is the longest step")
        import uvicorn
        from app_masaustu import app

        pencere.bildir("Sunucu hazırlanıyor  ·  Preparing server", "")
        port = free_port()

        # log_config=None -> uvicorn kendi günlük yapılandırmasını KURMAZ.
        # Pencereli modda stdout olmadığı için bu şart.
        config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                log_level="critical", access_log=False,
                                log_config=None)
        server = uvicorn.Server(config)
        pencere.server = server

        def ac():
            time.sleep(1.0)
            try:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            except Exception:
                pass
            pencere.root.after(0, lambda: pencere.hazir_ekrani(port))

        threading.Thread(target=ac, daemon=True).start()
        server.run()

    except Exception as e:
        import traceback
        iz = traceback.format_exc()
        pencere.root.after(0, lambda: pencere.hata_ekrani(f"{e}\n\n{iz}"))


def main():
    try:
        pencere = Pencere()
    except Exception as e:
        print(f"Pencere açılamadı: {e}")
        return 1

    threading.Thread(target=sunucuyu_baslat, args=(pencere,), daemon=True).start()
    pencere.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
