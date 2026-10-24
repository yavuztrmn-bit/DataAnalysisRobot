# Data Analysis Robot — Masaüstü Sürüm

plssem.com motorunu kullanıcının kendi bilgisayarında çalıştıran paket program.

---

## Neden

| | Web sürümü | Masaüstü sürüm |
|---|---|---|
| İşlemci | Sunucu (1 çekirdek kotası) | Kullanıcının bilgisayarı, tüm çekirdekler |
| Eşzamanlı kullanıcı | Sırayla, 1 kişi | Sınırsız (herkes kendi makinesinde) |
| İnternet | Gerekli | Gerekmez |
| Veri | Sunucuya gönderilir | Bilgisayardan hiç çıkmaz |
| Büyük model | CPU kotası riski | Sorunsuz |

---

## Nasıl çalışır

Kullanıcı `DataAnalysisRobot.exe`'ye çift tıklar. Program:

1. Bilgisayarda boş bir port bulur (yalnızca `127.0.0.1` — dışarıya **kapalı**)
2. FastAPI sunucusunu arka planda başlatır
3. Varsayılan tarayıcıda arayüzü açar
4. Konsol penceresi kapatılınca sunucu da kapanır

Kullanıcı açısından fark yok; aynı arayüzü görür. Analiz kendi makinesinde çalışır.

---

## Derleme (bir kez, sizin bilgisayarınızda)

**Not:** Windows `.exe` yalnızca Windows'ta derlenebilir. macOS sürümü için Mac gerekir.

### Gerekenler
- Windows 10 veya 11
- Python 3.11 ya da 3.12 ([python.org](https://python.org))
  Kurulumda **"Add Python to PATH"** seçeneğini işaretleyin.

### Adımlar

**1.** Boş bir klasör açın, şu dosyaları içine kopyalayın:

*Bu paketten:*
```
baslatici.py
DataAnalysisRobot.spec
DataAnalysisRobot.ico
surum_bilgisi.txt
gereksinimler.txt
DERLE.bat
logo_256.png
```

*Sunucunuzdan:*
```
app.py
plssem.py
fit_indices.py
cfa_engine.py
analysis_queue.py
pls-sem.html
ornek_veri.xlsx      (isteğe bağlı)
pls-sem-v2/          (varsa)
```

**2.** `DERLE.bat` dosyasına çift tıklayın.

Sanal ortam kurar, bağımlılıkları indirir, `.exe` üretir. İlk seferde 10-20 dakika sürer.

**3.** Sonuç: `dist\DataAnalysisRobot.exe`

Bu tek dosyayı dağıtabilirsiniz. Kullanıcının Python kurmasına gerek yoktur.

---

## Derleme öncesi kontrol

Derlemeden önce başlatıcıyı doğrudan çalıştırıp test edin:

```
python baslatici.py
```

Tarayıcı açılıp analiz çalışıyorsa derlemeye geçebilirsiniz. Bu adım, sorunu 15 dakikalık derlemeden sonra değil, 10 saniyede görmenizi sağlar.

---

## Yapılması gerekenler

### 1. Lisans sistemi

Masaüstü sürümde `keys.json` **paketlenmiyor**. Şu anki key doğrulama sunucuya bağlı; `.exe` içinde çalışmaz.

Üç seçenek:

**a) Lisanssız dağıtım** — Ücretsiz sürüm olarak verirsiniz. En basiti.

**b) Çevrimdışı lisans** — Kullanıcının makine kimliğinden üretilen bir anahtar. İnternet gerekmez ama üretim/dağıtım sistemi kurmanız gerekir.

**c) Çevrimiçi doğrulama** — İlk açılışta plssem.com'a sorar, sonra yerel olarak saklar. Mevcut altyapınızı kullanır ama internet gerektirir.

Hangisini istediğinizi söylerseniz o kısmı yazarım.

### 2. Kod imzalama (önerilir)

İmzasız `.exe` dosyalarında Windows SmartScreen "Bilinmeyen yayımcı" uyarısı verir ve bazı antivirüsler yanlış pozitif üretir. Kod imzalama sertifikası (yıllık ~100-300 USD) bunu çözer.

İmzasız dağıtacaksanız kullanıcılara "Daha fazla bilgi → Yine de çalıştır" adımını anlatan bir not ekleyin.

---

## Bilinmesi gerekenler

**Dosya boyutu 200-400 MB.** numpy, scipy, pandas ve semopy'nin kaçınılmaz maliyeti. UPX kuruluysa bir miktar küçülür.

**İlk açılış 5-10 saniye sürer.** Tek dosyalı `.exe` her çalıştırmada kendini geçici klasöre açar. Daha hızlı açılış isterseniz `.spec` dosyasında klasörlü derlemeye geçilebilir; o zaman `.exe` + yanında klasör olur.

**Kod korunmaz.** PyInstaller şifreleme değil paketlemedir; isteyen içeriği çıkarabilir. Motorunuzun kopyalanması sizin için önemliyse bu ciddi bir kısıttır.

**Güncelleme.** Web'de dosyayı değiştirip bitiriyorsunuz; pakette her düzeltme için yeni sürüm dağıtmanız gerekir.

**Antivirüs.** PyInstaller çıktıları sıkça yanlış pozitif verir. VirusTotal'e yükleyip kontrol etmenizi öneririm.

---

## Web sürümünü kapatmayın

İkisi birlikte dursun:

- **Web** — ücretsiz, deneme, küçük modeller, hızlı erişim
- **Masaüstü** — ücretli, büyük veri setleri, kurumsal kullanım, veri gizliliği

Bu hem gelir modeli olur hem de CPU sorununu kalıcı çözer. Veri güvenliği gerekçesiyle bulut kullanamayan kurumlar için de masaüstü sürüm gerçek bir ihtiyaçtır.

---

## Sorun giderme

**"ModuleNotFoundError" derleme sonrası**
`.spec` dosyasındaki `hiddenimports` listesine eksik modülü ekleyin, yeniden derleyin.

**"app.py bulunamadı"**
`app.py` ve diğer Python dosyaları `baslatici.py` ile aynı klasörde olmalı.

**Tarayıcı açılmıyor**
Konsoldaki adresi (`http://127.0.0.1:8756`) elle yapıştırın.

**Analiz çalışmıyor**
Konsol penceresindeki hata mesajına bakın; masaüstü sürümde hatalar orada görünür.
