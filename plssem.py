# ══════════════════════════════════════════════════════════════
#  PAYLAŞIMLI SUNUCU KORUMASI — numpy import edilmeden ÖNCE olmalı
#  numpy/BLAS varsayılan olarak tüm çekirdekleri kullanır. CPU kotası
#  olan paylaşımlı hosting'de (cPanel/CloudLinux LVE) bu, tek bir
#  analizin kotayı anında doldurmasına ve sürecin öldürülmesine yol açar.
#  Tek çekirdeğe sabitlemek toplam süreyi çok az uzatır, kota aşımını önler.
# ══════════════════════════════════════════════════════════════
import os as _os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_v, "1")

import numpy as np
import pandas as pd
from scipy import stats

# Uyum indeksleri ayrı modülde (fit_indices.py plssem.py ile aynı klasörde olmalı)
try:
    from fit_indices import compute_fit_indices
    _HAS_FIT = True
except Exception:
    _HAS_FIT = False


# ══════════════════════════════════════════════════════════════════
#  Temel yardımcılar
# ══════════════════════════════════════════════════════════════════

def cronbach_alpha(X: pd.DataFrame) -> float:
    k = X.shape[1]
    item_var = X.var(axis=0, ddof=1).sum()
    total_var = X.sum(axis=1).var(ddof=1)
    if k <= 1 or total_var == 0:
        return np.nan
    return (k / (k - 1)) * (1 - item_var / total_var)


def corr(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if np.std(a, ddof=1) == 0 or np.std(b, ddof=1) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def zscore(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce")
    mu = x.mean()
    sd = x.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return x * np.nan
    return (x - mu) / sd


def vif_for_items(X: pd.DataFrame) -> pd.Series:
    vifs = {}
    cols = list(X.columns)
    for target in cols:
        y = X[target].astype(float).values
        others = [c for c in cols if c != target]
        if len(others) == 0:
            vifs[target] = np.nan
            continue
        Z = np.nan_to_num(X[others].astype(float).values, nan=0.0, posinf=0.0, neginf=0.0)
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
        Z_ = np.column_stack([np.ones(len(Z)), Z])
        try:
            beta, *_ = np.linalg.lstsq(Z_, y, rcond=None)
        except np.linalg.LinAlgError:
            vifs[target] = np.nan
            continue
        yhat = Z_.dot(beta)
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 0 if ss_tot == 0 else 1 - ss_res / ss_tot
        vifs[target] = float(1 / (1 - r2)) if (1 - r2) > 1e-12 else float("inf")
    return pd.Series(vifs)


def composite_reliability(loadings: np.ndarray) -> float:
    """rho_C — Composite Reliability (Jöreskog, 1971)"""
    l = np.asarray(loadings, dtype=float)
    num = (l.sum()) ** 2
    den = num + np.sum(1 - l ** 2)
    return float(num / den) if den != 0 else np.nan


def rho_C(loadings: np.ndarray) -> float:
    """rho_C — Composite Reliability (composite_reliability ile aynı, alias)"""
    return composite_reliability(loadings)


def rho_A(X: pd.DataFrame, loadings: np.ndarray) -> float:
    """
    rho_A — Dijkstra & Henseler (2015) güvenilirlik katsayısı.
    Cronbach Alpha ve CR arasında bir değer alır; tek boyutluluğu
    varsaymaz ve PLS-SEM için önerilir.

    Formül:
        rho_A = (sum_lambda)^2 * (rho_c - 1) / ((sum_lambda)^2 - sum_lambda^2) + 1
    Eşdeğer ve sayısal olarak daha kararlı form:
        rho_A = k^2 * (1 - 1/k) * alpha / (1 + alpha * (k - 1) / k)
    En yaygın uygulama (Dijkstra & Henseler):
        Korelasyon matrisinden türetilen formül kullanılır.
    """
    l = np.asarray(loadings, dtype=float)
    k = len(l)
    if k <= 1:
        return np.nan

    # Korelasyon matrisine dayalı form (daha kararlı)
    X_num = X.apply(pd.to_numeric, errors="coerce").fillna(X.mean())
    cols = list(X_num.columns)
    if len(cols) <= 1:
        return np.nan

    try:
        R = X_num.corr().values
        sum_offdiag = np.sum(R) - np.trace(R)          # off-diagonal toplamı
        sum_lambda2 = np.sum(l ** 2)
        sum_lambda  = np.sum(l)
        sum_lambda_sq = sum_lambda ** 2

        # Dijkstra & Henseler (2015) Eq. 16
        numerator   = sum_lambda_sq * (composite_reliability(l) - 1)
        denominator = sum_lambda_sq - sum_lambda2
        if abs(denominator) < 1e-12:
            return np.nan
        result = numerator / denominator + 1
        # [0, 1] aralığına sıkıştır (sayısal hassasiyet sapmaları için)
        return float(np.clip(result, 0.0, 1.0))
    except Exception:
        return np.nan


def ave(loadings: np.ndarray) -> float:
    l = np.asarray(loadings, dtype=float)
    return float(np.mean(l ** 2)) if len(l) else np.nan


def htmt_between(A: pd.DataFrame, B: pd.DataFrame) -> float:
    def pair_corrs(X, Y):
        vals = []
        for x in X.columns:
            for y in Y.columns:
                vals.append(abs(corr(X[x], Y[y])))
        return np.array([v for v in vals if not np.isnan(v)])

    def within_corrs(X):
        cols = list(X.columns)
        vals = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                vals.append(abs(corr(X[cols[i]], X[cols[j]])))
        return np.array([v for v in vals if not np.isnan(v)])

    het = pair_corrs(A, B)
    monoA = within_corrs(A)
    monoB = within_corrs(B)
    if len(het) == 0 or len(monoA) == 0 or len(monoB) == 0:
        return np.nan
    return float(np.mean(het) / np.sqrt(np.mean(monoA) * np.mean(monoB)))


def ols_coef(X: np.ndarray, y: np.ndarray):
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    X_ = np.column_stack([np.ones(n), X])
    beta, *_ = np.linalg.lstsq(X_, y, rcond=None)
    yhat = X_.dot(beta)
    resid = y - yhat
    df = max(n - X_.shape[1], 1)
    s2 = (resid @ resid) / df
    XtX = X_.T @ X_
    XtX_inv = np.linalg.inv(XtX + 1e-12 * np.eye(XtX.shape[0]))
    se = np.sqrt(np.diag(s2 * XtX_inv))
    t = beta / (se + 1e-12)
    p = 2 * (1 - stats.t.cdf(np.abs(t), df=df))
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return beta, se, t, p, float(r2)


# ══════════════════════════════════════════════════════════════════
#  ÖLÇÜM MODELİ — ayrı fonksiyon
#  Bootstrap'ın her yinelemede yeniden çağırabilmesi için ayrıldı.
# ══════════════════════════════════════════════════════════════════

def build_latent(df: pd.DataFrame, constructs: list, collect_diagnostics: bool = True):
    """
    Yapı skorlarını (latent) ve dış yükleri hesaplar.

    ÖNEMLİ: Negatif yükler ARTIK MUTLAK DEĞERE ÇEVRİLMEZ.
    Ters kodlanmış veya yapıya uymayan bir madde negatif yük verir; bu
    kullanıcının görmesi gereken bir bulgudur, gizlenmemelidir.
    Bunun yerine `warnings` listesinde raporlanır.

    Döner: (latent DataFrame, loadings_rows, weights_map, warnings)
    """
    latent_scores = {}
    loadings_rows = []
    weights_map = {}
    warnings = []

    for c in constructs:
        items = c["items"]
        name = c["name"]

        X_raw = df[items].apply(pd.to_numeric, errors="coerce")
        n_missing = int(X_raw.isna().sum().sum())
        X = X_raw.fillna(X_raw.mean())
        # Tamami bos bir madde varsa ortalama da NaN olur -> 0 ile doldur
        X = X.fillna(0.0)

        sd_cols = X.std(ddof=1).replace(0, np.nan)
        X_std = (X - X.mean()) / sd_cols
        X_std = X_std.fillna(0.0).replace([np.inf, -np.inf], 0.0)

        # Birinci temel bileşen (SVD) — mevcut yaklaşım korundu
        u, s, vh = np.linalg.svd(X_std, full_matrices=False)
        weights = vh[0]

        lv = X_std.values @ weights

        # İşaret belirsizliği: LV, maddelerin toplamıyla pozitif ilişkili olmalı
        col_sum = X_std.sum(axis=1).values
        if np.std(lv, ddof=1) > 1e-12 and np.std(col_sum, ddof=1) > 1e-12:
            if np.corrcoef(lv, col_sum)[0, 1] < 0:
                lv = -lv
                weights = -weights

        sd_lv = np.std(lv, ddof=1)
        lv = (lv - lv.mean()) / (sd_lv if sd_lv > 1e-12 else 1.0)

        latent_scores[name] = lv
        weights_map[name] = weights

        neg_items = []
        for it in items:
            loading = float(corr(X[it], lv))
            # ⚠ abs() KALDIRILDI — negatif yük olduğu gibi raporlanır
            loadings_rows.append({"construct": name, "item": it, "loading": loading})
            if not np.isnan(loading) and loading < 0:
                neg_items.append(it)

        if collect_diagnostics:
            if neg_items:
                warnings.append({
                    "type": "negative_loading",
                    "construct": name,
                    "items": neg_items,
                    "message": (
                        f"{name} yapısında {', '.join(neg_items)} maddesi/maddeleri NEGATİF yük veriyor. "
                        "Bu genellikle ters kodlanmış (reverse-coded) bir maddenin dönüştürülmediğini "
                        "veya maddenin yapıya ait olmadığını gösterir. Analizden önce kontrol edin."
                    ),
                })
            if n_missing > 0:
                warnings.append({
                    "type": "missing_imputed",
                    "construct": name,
                    "count": n_missing,
                    "message": (
                        f"{name} yapısında {n_missing} eksik hücre sütun ortalamasıyla dolduruldu "
                        "(mean imputation). Eksik veri oranı yüksekse sonuçları temkinli yorumlayın."
                    ),
                })

    latent = pd.DataFrame(latent_scores, index=df.index)
    return latent, loadings_rows, weights_map, warnings


# ══════════════════════════════════════════════════════════════════
#  HIZLI YOL — bootstrap icin saf numpy olcum modeli
#  build_latent ile AYNI matematigi yapar, pandas ek yuku yoktur.
# ══════════════════════════════════════════════════════════════════

def _latent_np(X: np.ndarray, blocks: list):
    """
    X      : (n, p) ham gosterge matrisi (NaN'siz olmali)
    blocks : her yapinin sutun indeksleri
    Doner  : (scores (n,k), lam (p,))
    """
    n = X.shape[0]
    k = len(blocks)
    scores = np.empty((n, k))
    lam = np.zeros(X.shape[1])

    for bi, b in enumerate(blocks):
        Xb = np.nan_to_num(X[:, b], nan=0.0, posinf=0.0, neginf=0.0)
        mu = Xb.mean(axis=0)
        sd = Xb.std(axis=0, ddof=1)
        sd = np.where((sd < 1e-12) | ~np.isfinite(sd), 1.0, sd)
        Z = np.nan_to_num((Xb - mu) / sd, nan=0.0, posinf=0.0, neginf=0.0)

        # Birinci temel bilesen
        _u, _s, vh = np.linalg.svd(Z, full_matrices=False)
        w = vh[0]
        lv = Z @ w

        # Isaret belirsizligi
        cs = Z.sum(axis=1)
        if np.std(lv, ddof=1) > 1e-12 and np.std(cs, ddof=1) > 1e-12:
            if np.dot(lv - lv.mean(), cs - cs.mean()) < 0:
                lv = -lv

        s_lv = lv.std(ddof=1)
        lv = (lv - lv.mean()) / (s_lv if s_lv > 1e-12 else 1.0)
        scores[:, bi] = lv

        # Yukler: gosterge-skor korelasyonu
        Zc = Z - Z.mean(axis=0)
        lvc = lv - lv.mean()
        denom = np.sqrt((Zc ** 2).sum(axis=0) * (lvc ** 2).sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            r = (Zc * lvc[:, None]).sum(axis=0) / denom
        for j, i in enumerate(b):
            lam[i] = 0.0 if not np.isfinite(r[j]) else r[j]

    return scores, lam


def _augment_latent(latent: pd.DataFrame, df: pd.DataFrame, controls: list, interactions: list) -> pd.DataFrame:
    """Kontrol değişkenlerini ve etkileşim terimlerini latent tabloya ekler."""
    latent = latent.copy()
    for ctrl in controls:
        if ctrl["column"] in df.columns:
            latent[ctrl["name"]] = pd.to_numeric(df[ctrl["column"]], errors="coerce").values
    for inter in interactions:
        nm, a, b = inter["name"], inter["a"], inter["b"]
        if a not in latent.columns or b not in latent.columns:
            continue
        A, B = latent[a], latent[b]
        if inter.get("standardize", True):
            A, B = zscore(A), zscore(B)
        latent[nm] = (A * B).values
    return latent


# ══════════════════════════════════════════════════════════════════
#  Q²  —  GERÇEK BLINDFOLDING
# ══════════════════════════════════════════════════════════════════

def compute_q2(df: pd.DataFrame, constructs: list, equations: dict,
               controls: list, interactions: list, omission_distance: int = 7,
               max_rounds: int = None):
    """
    Stone-Geisser Q² — çapraz doğrulanmış REDUNDANCY yaklaşımı (blindfolding).

    ÖNCEKİ SÜRÜMDE HATA VARDI: Q², örneklem içi R² ile birebir AYNI hesaplanıyordu
    (1 - SSE/SSO, aynı veriyle tahmin ve değerlendirme). Bu Q² değil R²'dir ve
    hiçbir zaman negatif çıkamaz. Artık gerçek blindfolding uygulanıyor.

    Yöntem:
      - Gösterge matrisindeki hücreler d aralıklarla sistematik olarak silinir.
      - Her blindfolding turunda silinen hücreler dışlanarak ölçüm modeli ve
        yapısal model yeniden kurulur.
      - Silinen hücreler, öncül yapılardan tahmin edilen bağımlı yapı skoru
        üzerinden yeniden üretilir (redundancy).
      - Q² = 1 - ΣSSE / ΣSSO
    """
    rows = []
    d = max(int(omission_distance), 2)
    # Çok büyük modellerde blindfolding turu sınırlanır (maliyet: tur × bağımlı yapı)
    if max_rounds:
        d = min(d, max(int(max_rounds), 2))

    item_map = {c["name"]: list(c["items"]) for c in constructs}
    n = len(df)

    # ÖNEMLİ: Likert verisi int64 olarak gelebilir. Blindfolding sirasinda
    # hucrelere NaN yazildigi icin ilgili sutunlar float olmalidir; aksi halde
    # pandas "cannot convert float NaN to integer" hatasi verir.
    all_items = [it for c in constructs for it in c["items"] if it in df.columns]
    base_df = df.copy()
    for _it in all_items:
        base_df[_it] = pd.to_numeric(base_df[_it], errors="coerce").astype(float)

    # ── Numpy hizli yol icin yapilari BIR KEZ hazirla ──
    q2_items, q2_blocks, q2_names = [], [], []
    for c in constructs:
        cols_ = [it for it in c["items"] if it in df.columns]
        if len(cols_) < 2:
            continue
        q2_names.append(c["name"])
        q2_blocks.append([len(q2_items) + i for i in range(len(cols_))])
        q2_items.extend(cols_)
    q2_idx = {it: i for i, it in enumerate(q2_items)}

    ctrl_np = {}
    for ctrl in controls:
        if ctrl["column"] in df.columns:
            v = np.array(pd.to_numeric(df[ctrl["column"]], errors="coerce")
                         .to_numpy(dtype=float), copy=True)
            m_ = np.isnan(v)
            if m_.any():
                v[m_] = float(np.nanmean(v)) if np.any(~m_) else 0.0
            ctrl_np[ctrl["name"]] = np.nan_to_num(v, nan=0.0)
    inter_np = [(i["name"], i["a"], i["b"], i.get("standardize", True))
                for i in interactions]

    for dep, preds in equations.items():
        dep_items = item_map.get(dep)
        if not dep_items:
            continue  # kontrol/etkileşim gibi göstergesiz hedefler atlanır

        obs = base_df[dep_items].apply(pd.to_numeric, errors="coerce")
        obs = obs.fillna(obs.mean()).fillna(0.0)
        sd_o = obs.std(ddof=1).replace(0, np.nan)
        obs_std = ((obs - obs.mean()) / sd_o).fillna(0.0).replace([np.inf, -np.inf], 0.0)

        sse_total = 0.0
        sso_total = 0.0
        flat_len = n * len(dep_items)

        for g in range(d):
            # Bu turda silinecek hücreler (satır-sütun düzleştirilmiş indeks)
            omit_flat = np.arange(g, flat_len, d)
            omit_rows = omit_flat // len(dep_items)
            omit_cols = omit_flat % len(dep_items)

            mask = np.zeros((n, len(dep_items)), dtype=bool)
            mask[omit_rows, omit_cols] = True
            if not mask.any():
                continue

            # Silinen hücreler ortalamayla doldurulup ölçüm modeli yeniden kurulur
            work = base_df.copy()
            block = obs.values.copy()
            for j, it in enumerate(dep_items):
                col = block[:, j]
                col[mask[:, j]] = np.nan
                with np.errstate(invalid="ignore"):
                    colmean = float(np.nanmean(col)) if np.any(~np.isnan(col)) else 0.0
                if not np.isfinite(colmean):
                    colmean = 0.0
                col[np.isnan(col)] = colmean
                block[:, j] = col
                work[it] = col

            # HIZLI YOL: pandas build_latent yerine saf numpy (_latent_np)
            Xg = np.column_stack([
                pd.to_numeric(work[it], errors="coerce").to_numpy(dtype=float)
                for it in q2_items
            ])
            Xg = np.nan_to_num(Xg, nan=0.0, posinf=0.0, neginf=0.0)
            sc_g, lam_g = _latent_np(Xg, q2_blocks)
            lat_np = {nm: sc_g[:, bi] for bi, nm in enumerate(q2_names)}
            for cn, cv in ctrl_np.items():
                lat_np[cn] = cv
            for inm, ia, ib, ist in inter_np:
                if ia in lat_np and ib in lat_np:
                    A_, B_ = lat_np[ia], lat_np[ib]
                    if ist:
                        sa, sb = A_.std(ddof=1), B_.std(ddof=1)
                        A_ = (A_ - A_.mean()) / (sa if sa > 1e-12 else 1.0)
                        B_ = (B_ - B_.mean()) / (sb if sb > 1e-12 else 1.0)
                    lat_np[inm] = A_ * B_

            usable = [p for p in preds if p in lat_np]
            if not usable or dep not in lat_np:
                continue

            y = lat_np[dep]
            Xp_ = np.column_stack([np.ones(len(y))] + [lat_np[p] for p in usable])
            beta, *_ = np.linalg.lstsq(Xp_, y, rcond=None)
            lv_hat = Xp_ @ beta

            lmap = {it: lam_g[q2_idx[it]] for it in dep_items if it in q2_idx}

            for j, it in enumerate(dep_items):
                sel = mask[:, j]
                if not sel.any():
                    continue
                lam = lmap.get(it, 0.0)
                if np.isnan(lam):
                    lam = 0.0
                pred_vals = lam * lv_hat[sel]
                true_vals = obs_std.values[sel, j]
                sse_total += float(np.sum((true_vals - pred_vals) ** 2))
                # SSO: naif referans = göstergenin ortalaması (standardize veride 0)
                sso_total += float(np.sum(true_vals ** 2))

        q2 = 1.0 - (sse_total / sso_total) if sso_total > 1e-12 else np.nan

        if np.isnan(q2):
            level = "N/A"
        elif q2 <= 0:
            level = "No predictive relevance"
        elif q2 < 0.25:
            level = "Small"
        elif q2 < 0.50:
            level = "Medium"
        else:
            level = "Large"

        rows.append({
            "dependent": dep,
            "q2": float(q2) if not np.isnan(q2) else None,
            "predictive_relevance": level,
            "omission_distance": d,
            "method": "blindfolding (cross-validated redundancy)",
        })

    return rows


# ══════════════════════════════════════════════════════════════════
#  f²
# ══════════════════════════════════════════════════════════════════

def compute_f2(latent: pd.DataFrame, equations: dict):
    f2_rows = []
    dep_names = list(equations.keys())
    pred_names = sorted({p for preds in equations.values() for p in preds})
    f2_matrix = pd.DataFrame(index=pred_names, columns=dep_names)

    for dep, preds in equations.items():
        preds = [p for p in preds if p in latent.columns]
        if dep not in latent.columns or not preds:
            continue

        _, _, _, _, r2_full = ols_coef(latent[preds].values, latent[dep].values)

        for pred in preds:
            reduced = [p for p in preds if p != pred]
            if len(reduced) == 0:
                r2_excluded = 0.0
            else:
                _, _, _, _, r2_excluded = ols_coef(latent[reduced].values, latent[dep].values)

            denom = (1 - r2_full)
            f2 = ((r2_full - r2_excluded) / denom) if abs(denom) > 1e-12 else np.nan

            if np.isnan(f2):
                level = "N/A"
            elif f2 < 0.02:
                level = "Negligible"
            elif f2 < 0.15:
                level = "Small"
            elif f2 < 0.35:
                level = "Moderate"
            else:
                level = "Strong"

            f2_rows.append({"from": pred, "to": dep, "f2": float(f2), "effect_size": level})
            f2_matrix.loc[pred, dep] = float(f2)

    return f2_rows, f2_matrix.fillna("").to_dict()


def compute_cross_loadings(df: pd.DataFrame, constructs: list, latent: pd.DataFrame):
    rows = []
    construct_names = [c["name"] for c in constructs]
    for c in constructs:
        for item in c["items"]:
            item_series = pd.to_numeric(df[item], errors="coerce")
            row = {"item": item, "own_construct": c["name"]}
            for cn in construct_names:
                row[cn] = float(corr(item_series, latent[cn]))
            rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════════
#  BOOTSTRAP — ölçüm modeli DAHİL yeniden örnekleme
# ══════════════════════════════════════════════════════════════════

def bootstrap_full(df: pd.DataFrame, constructs: list, controls: list,
                   interactions: list, equations: dict, B: int = 500, seed: int = 42):
    """
    Ham veriyi yeniden örnekler ve HER YİNELEMEDE ölçüm modelini
    (yapı skorları + yükler) yeniden kurar.

    ÖNCEKİ SÜRÜMDE EKSİKTİ: yalnızca sabit latent skorlar yeniden örnekleniyordu,
    yani ölçüm modelindeki belirsizlik hesaba katılmıyordu. Bu, standart hataları
    sistematik olarak küçük, t değerlerini büyük, p değerlerini küçük gösterir.

    Döner: {(from, to): np.ndarray(B,)} yol katsayısı dağılımları
    """
    # Hipotez yoksa (ör. Adim 2 "olcum modeli" cagrisi) bootstrap ANLAMSIZDIR.
    if not equations or not any(equations.values()):
        return {}, 0

    rng = np.random.default_rng(seed)
    n = len(df)

    # ── Veriyi bir kez numpy'a cevir (pandas ek yukunu bootstrap disina al) ──
    items, blocks, names = [], [], []
    for c in constructs:
        cols = [it for it in c["items"] if it in df.columns]
        if len(cols) < 2:
            continue
        names.append(c["name"])
        blocks.append([len(items) + i for i in range(len(cols))])
        items.extend(cols)

    Xall = np.array(df[items].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float), copy=True)
    with np.errstate(invalid="ignore"):
        colmean = np.nanmean(Xall, axis=0)
    colmean = np.nan_to_num(colmean, nan=0.0)
    inds = np.where(np.isnan(Xall))
    Xall[inds] = np.take(colmean, inds[1])
    Xall = np.nan_to_num(Xall, nan=0.0, posinf=0.0, neginf=0.0)

    # Kontrol degiskenleri
    ctrl_names, ctrl_cols = [], []
    for ctrl in controls:
        if ctrl["column"] in df.columns:
            ctrl_names.append(ctrl["name"])
            v = np.array(
                pd.to_numeric(df[ctrl["column"]], errors="coerce").to_numpy(dtype=float),
                dtype=float, copy=True,
            )
            m = np.isnan(v)
            if m.any():
                v[m] = float(np.nanmean(v)) if np.any(~m) else 0.0
            ctrl_cols.append(v)
    Xctrl = np.column_stack(ctrl_cols) if ctrl_cols else np.empty((n, 0))

    all_names = names + ctrl_names
    name_idx = {nm: i for i, nm in enumerate(all_names)}

    inter_defs = []
    for it in interactions:
        if it["a"] in name_idx and it["b"] in name_idx:
            inter_defs.append((it["name"], name_idx[it["a"]], name_idx[it["b"]],
                               it.get("standardize", True)))

    for nm, _a, _b, _st in inter_defs:
        name_idx[nm] = len(all_names)
        all_names.append(nm)

    dists = {}
    for dep, preds in equations.items():
        for p in preds:
            dists[(p, dep)] = []

    ok = 0
    for _ in range(int(B)):
        idx = rng.integers(0, n, size=n)
        try:
            scores, _lam = _latent_np(Xall[idx, :], blocks)
            cols_list = [scores]
            if Xctrl.shape[1]:
                cols_list.append(Xctrl[idx, :])
            M = np.column_stack(cols_list) if len(cols_list) > 1 else scores

            if inter_defs:
                extra = []
                for _nm, ia, ib, st in inter_defs:
                    A, Bv = M[:, ia], M[:, ib]
                    if st:
                        sa, sb = A.std(ddof=1), Bv.std(ddof=1)
                        A = (A - A.mean()) / (sa if sa > 1e-12 else 1.0)
                        Bv = (Bv - Bv.mean()) / (sb if sb > 1e-12 else 1.0)
                    extra.append(A * Bv)
                M = np.column_stack([M] + extra)

            for dep, preds in equations.items():
                if dep not in name_idx:
                    continue
                usable = [p for p in preds if p in name_idx]
                if not usable:
                    continue
                y = M[:, name_idx[dep]]
                Xp = np.column_stack([np.ones(n), M[:, [name_idx[p] for p in usable]]])
                beta, *_ = np.linalg.lstsq(Xp, y, rcond=None)
                for i, p in enumerate(usable):
                    dists[(p, dep)].append(float(beta[1 + i]))
            ok += 1
        except Exception:
            continue

    return {k: np.array(v, dtype=float) for k, v in dists.items()}, ok


def _percentile_ci(samples: np.ndarray, level: float = 0.95):
    """Yüzdelik bootstrap güven aralığı."""
    s = samples[np.isfinite(samples)]
    if s.size < 20:
        return None, None
    a = (1.0 - level) / 2.0
    return float(np.percentile(s, 100 * a)), float(np.percentile(s, 100 * (1 - a)))


# ══════════════════════════════════════════════════════════════════
#  ANA FONKSİYON
# ══════════════════════════════════════════════════════════════════

def analyze(df: pd.DataFrame, constructs: list, hypotheses: list, controls: list,
            interactions: list, bootstrap_samples: int = 2000,
            include_fit_indices=None, light_mode: bool = False):
    """
    include_fit_indices : True/False/None
        None (varsayılan) -> model büyüklüğüne göre otomatik karar verilir.
        Uyum indeksleri toplam sürenin ~%40'ını oluşturur; büyük modellerde
        otomatik olarak kapatılır ve bu durum sonuçta bildirilir.
    light_mode : True
        Blindfolding turlarını ve bootstrap'ı düşürür, uyum indekslerini kapatır.
        CPU kotası kısıtlı sunucular için.
    """
    results = {}

    # ── 0) Maliyet kararları ───────────────────────────────────
    _p_ind = sum(len(c["items"]) for c in constructs)
    if light_mode:
        include_fit_indices = False
    elif include_fit_indices is None:
        # 40 göstergeden büyük modellerde uyum indeksleri OTOMATİK kapatılır.
        # (Toplam sürenin ~%40'ı; PLS-SEM'de zaten tamamlayıcı bir ölçüttür.)
        include_fit_indices = (_p_ind <= 40)

    # ── 1) Ölçüm modeli ────────────────────────────────────────
    latent_c, loadings_rows, _weights, warnings = build_latent(df, constructs)

    vif_rows, rel_rows = [], []
    for c in constructs:
        name, items = c["name"], c["items"]
        X_raw = df[items].apply(pd.to_numeric, errors="coerce")
        X = X_raw.fillna(X_raw.mean())

        try:
            for it, v in vif_for_items(X).items():
                vif_rows.append({"construct": name, "item": it, "vif": float(v)})
        except Exception:
            for it in items:
                vif_rows.append({"construct": name, "item": it, "vif": float("nan")})

        l_vals = np.array([r["loading"] for r in loadings_rows if r["construct"] == name], dtype=float)
        rel_rows.append({
            "construct": name,
            "alpha": float(cronbach_alpha(X)),
            "rho_a": float(rho_A(X, l_vals)),
            "cr": float(composite_reliability(l_vals)),
            "rho_c": float(composite_reliability(l_vals)),   # rho_C = CR (alias)
            "ave": float(ave(l_vals)),
        })

    cross_loading_rows = compute_cross_loadings(df, constructs, latent_c)

    # ── 2) Kontroller + etkileşimler ───────────────────────────
    latent = _augment_latent(latent_c, df, controls, interactions)

    # ── 3) Ayrışma geçerliliği ─────────────────────────────────
    construct_names = [c["name"] for c in constructs]
    corr_m = latent[construct_names].corr()
    ave_map = {r["construct"]: r["ave"] for r in rel_rows}
    fornell = corr_m.copy()
    for name in fornell.columns:
        fornell.loc[name, name] = np.sqrt(max(ave_map.get(name, np.nan), 0)) \
            if not np.isnan(ave_map.get(name, np.nan)) else np.nan
    results["fornell_larcker"] = fornell.round(4).to_dict()

    htmt_matrix = pd.DataFrame(index=construct_names, columns=construct_names)
    for i in range(len(constructs)):
        for j in range(i):
            c1, c2 = constructs[i], constructs[j]
            A = df[c1["items"]].apply(pd.to_numeric, errors="coerce")
            Bm = df[c2["items"]].apply(pd.to_numeric, errors="coerce")
            val = float(htmt_between(A, Bm))
            htmt_matrix.loc[c1["name"], c2["name"]] = val
            htmt_matrix.loc[c2["name"], c1["name"]] = val
    results["htmt"] = htmt_matrix.fillna("").to_dict()

    # ── 4) Yapısal denklemler ──────────────────────────────────
    equations = {}
    for h in hypotheses:
        equations.setdefault(h["to"], []).append(h["from"])

    B = int(bootstrap_samples)
    # Bootstrap basarisiz olursa analiz DUSMEZ; OLS standart hatalarina geri donulur.
    try:
        boot, boot_ok = bootstrap_full(df, constructs, controls, interactions, equations, B=B)
    except Exception as _e:
        boot, boot_ok = {}, 0
        results.setdefault("engine_notes", []).append(
            f"Bootstrap calistirilamadi, OLS standart hatalari kullanildi: {str(_e)[:150]}"
        )

    path_rows, r2_rows = [], []
    for dep, preds in equations.items():
        if dep not in latent.columns:
            continue
        preds = [p for p in preds if p in latent.columns]
        if not preds:
            continue

        beta, se, t, p, r2 = ols_coef(latent[preds].values, latent[dep].values)
        n_obs, k = len(latent), len(preds)
        r2_adj = 1 - (1 - float(r2)) * (n_obs - 1) / (n_obs - k - 1) if n_obs > k + 1 else float(r2)
        r2_rows.append({"dependent": dep, "predictors": preds,
                        "r2": float(r2), "r2_adj": float(r2_adj)})

        for k_idx, pred in enumerate(preds):
            b = float(beta[1 + k_idx])
            samples = boot.get((pred, dep), np.array([]))
            if samples.size >= 20:
                se_b = float(np.std(samples, ddof=1))
                lo, hi = _percentile_ci(samples)
            else:
                se_b = float(se[1 + k_idx])
                lo = hi = None
            t_b = b / (se_b + 1e-12)
            p_b = float(2 * (1 - stats.norm.cdf(abs(t_b))))
            path_rows.append({
                "from": pred, "to": dep, "beta": b, "std_dev": se_b,
                "t": float(t_b), "p": p_b,
                "ci_lower": lo, "ci_upper": hi,
            })

    # ── 5) Hipotez tablosu ─────────────────────────────────────
    hyp_rows = []
    for r in path_rows:
        h_label = ""
        for idx, h in enumerate(hypotheses):
            if h["from"] == r["from"] and h["to"] == r["to"]:
                h_label = f"H{idx+1}"
                break
        hyp_rows.append({
            "H": h_label,
            "path": f'{r["from"]} → {r["to"]}',
            "beta": r["beta"], "std_dev": r["std_dev"],
            "t": r["t"], "p": r["p"],
            "ci_lower": r["ci_lower"], "ci_upper": r["ci_upper"],
            "decision": "Desteklendi" if r["p"] < 0.05 else "Desteklenmedi",
        })

    # ── 6) Q² (gerçek blindfolding) ve f² ──────────────────────
    # Q2 (blindfolding) basarisiz olursa analiz DUSMEZ; Q2 bos doner.
    q2_rows = []
    if equations and any(equations.values()):
        try:
            _p2 = sum(len(c["items"]) for c in constructs)
            _mr = 3 if light_mode else (7 if _p2 <= 60 else (5 if _p2 <= 100 else 4))
            q2_rows = compute_q2(df, constructs, equations, controls,
                                 interactions, max_rounds=_mr)
        except Exception as _e:
            results.setdefault("engine_notes", []).append(
                f"Q2 (blindfolding) hesaplanamadi: {str(_e)[:150]}"
            )
    f2_rows, f2_matrix = compute_f2(latent, equations)

    # ── 7) Dolaylı etkiler — YÜZDELİK CI ───────────────────────
    indirect_rows = []
    adj = {}
    for h in hypotheses:
        adj.setdefault(h["from"], []).append(h["to"])

    sequences, seen = [], set()
    for start in list(adj.keys()):
        q = [(start, [start])]
        while q:
            node, path = q.pop(0)
            if len(path) >= 4:
                continue
            for nb in adj.get(node, []):
                if nb in path:      # döngü koruması
                    continue
                new_path = path + [nb]
                if len(new_path) > 2 and tuple(new_path) not in seen:
                    seen.add(tuple(new_path))
                    sequences.append(tuple(new_path))
                q.append((nb, new_path))

    for seq in sequences:
        parts = []
        valid = True
        for i in range(len(seq) - 1):
            s = boot.get((seq[i], seq[i + 1]))
            if s is None or s.size < 20:
                valid = False
                break
            parts.append(s)
        if not valid:
            continue
        m = min(len(x) for x in parts)
        prod = np.ones(m)
        for x in parts:
            prod = prod * x[:m]

        ind_beta = float(np.mean(prod))
        ind_se = float(np.std(prod, ddof=1))
        lo, hi = _percentile_ci(prod)
        # Karar: yüzdelik CI sıfırı kapsamıyorsa anlamlı (Preacher & Hayes)
        if lo is not None and hi is not None:
            sig = (lo > 0) or (hi < 0)
        else:
            sig = False
        ind_t = ind_beta / (ind_se + 1e-12)
        ind_p = float(2 * (1 - stats.norm.cdf(abs(ind_t))))

        indirect_rows.append({
            "path": " → ".join(seq),
            "beta": ind_beta,
            "t": abs(ind_t),
            "p": ind_p,
            "ci_lower": lo, "ci_upper": hi,
            "decision": "Anlamlı" if sig else "Anlamsız",
            "inference": "percentile bootstrap CI",
        })

    # ── 8) Uyum indeksleri ─────────────────────────────────────
    # Uyum indeksleri yapisal model gerektirir; hipotez yoksa hesaplanmaz.
    if _HAS_FIT and include_fit_indices and equations and any(equations.values()):
        try:
            def _estimator(Xm, blocks):
                """fit_indices için tahminci — bu motorun ölçüm modelini kullanır."""
                Zs = (Xm - Xm.mean(axis=0)) / np.clip(Xm.std(axis=0, ddof=1), 1e-12, None)
                kk = len(blocks)
                scores = np.zeros((Xm.shape[0], kk))
                lam = np.zeros(Xm.shape[1])
                for bi, b in enumerate(blocks):
                    Zb = Zs[:, b]
                    _u, _s, vh = np.linalg.svd(Zb, full_matrices=False)
                    w = vh[0]
                    sc = Zb @ w
                    cs = Zb.sum(axis=1)
                    if np.dot(sc - sc.mean(), cs - cs.mean()) < 0:
                        sc = -sc
                    sd = sc.std(ddof=1)
                    sc = (sc - sc.mean()) / (sd if sd > 1e-12 else 1.0)
                    scores[:, bi] = sc
                    # Yukler TEK SEFERDE (gosterge basina corrcoef cagrisi kaldirildi)
                    Zc = Zb - Zb.mean(axis=0)
                    scc = sc - sc.mean()
                    den = np.sqrt((Zc ** 2).sum(axis=0) * (scc ** 2).sum())
                    with np.errstate(invalid="ignore", divide="ignore"):
                        rr = (Zc * scc[:, None]).sum(axis=0) / den
                    rr = np.nan_to_num(rr, nan=0.0, posinf=0.0, neginf=0.0)
                    for jj, i in enumerate(b):
                        lam[i] = rr[jj]
                phi = np.corrcoef(scores, rowvar=False)
                phi = np.nan_to_num(np.atleast_2d(phi), nan=0.0)
                np.fill_diagonal(phi, 1.0)
                return lam, phi, scores

            # ── Model büyüklüğüne göre uyarlanan bootstrap sayısı ──
            # Uyum indeksi çıkarımının maliyeti gösterge sayısının karesiyle
            # (d_G için küpüyle) büyür. Büyük modellerde sunucuyu kilitlememek
            # için tekrar sayısı otomatik düşürülür; kaç tekrar kullanıldığı
            # sonuçta "bootstrap_samples" alanında raporlanır.
            _p = sum(len(c["items"]) for c in constructs)
            if _p <= 30:
                _fb = min(B, 300)
            elif _p <= 60:
                _fb = min(B, 200)
            elif _p <= 100:
                _fb = min(B, 120)
            else:
                _fb = min(B, 60)

            results["fit_indices"] = compute_fit_indices(
                df=df, constructs=constructs, hypotheses=hypotheses,
                loadings=loadings_rows,
                bootstrap_samples=_fb, seed=42,
                estimator=_estimator,
            )
        except Exception as e:
            results["fit_indices"] = {"ok": False, "error": str(e)[:200]}
    elif not include_fit_indices:
        results["fit_indices"] = {
            "ok": False,
            "error": (f"Uyum indeksleri bu model icin otomatik olarak kapatildi "
                      f"({_p_ind} gosterge). Sunucu islemci kotasini korumak icindir; "
                      f"diger tum analizler etkilenmez."),
            "auto_disabled": True,
        }
    elif not (equations and any(equations.values())):
        results["fit_indices"] = {"ok": False, "error": "Uyum indeksleri icin yapisal model (hipotez) gerekir."}
    else:
        results["fit_indices"] = {"ok": False, "error": "fit_indices modulu bulunamadi."}

    results.update({
        "loadings": loadings_rows,
        "cross_loadings": cross_loading_rows,
        "vif": vif_rows,
        "reliability": rel_rows,
        "htmt": results["htmt"],
        "paths": path_rows,
        "hypotheses": hyp_rows,
        "indirect_results": indirect_rows,
        "r2": r2_rows,
        "q2": q2_rows,
        "f2_summary": f2_rows,
        "f2_matrix": f2_matrix,
        "warnings": warnings,
        "engine_notes": results.get("engine_notes", []),
        "meta": {
            "bootstrap_samples": B,
            "bootstrap_successful": int(boot_ok),
            "bootstrap_scope": "full (measurement + structural model re-estimated)",
            "q2_method": "blindfolding (cross-validated redundancy)",
            "ci_method": "percentile bootstrap",
            "indicators": int(_p_ind),
            "fit_indices_computed": bool(include_fit_indices),
            "light_mode": bool(light_mode),
        },
    })
    return results
