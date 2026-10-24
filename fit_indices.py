"""
fit_indices.py — PLS-SEM model uyum indeksleri (composite model)

Literatür:
  Dijkstra, T. K., & Henseler, J. (2015). Consistent partial least squares
      path modeling. MIS Quarterly, 39(2), 297-316.
  Henseler, J., Hubona, G., & Ray, P. A. (2016). Using PLS path modeling in
      new technology research: updated guidelines. IMDS, 116(1), 2-20.
  Henseler, J. et al. (2014). Common beliefs and reality about PLS. ORM, 17(2).

Bu modül şunları yapar ve mevcut JS uygulamasındaki dört sorunu giderir:

  1. SATURATED ve ESTIMATED model GERÇEKTEN ayrışır.
     - saturated : yapılar arası korelasyonlar serbest (gözlenen kompozit korelasyonları)
     - estimated : yapılar arası korelasyonlar YAPISAL MODELDEN türetilir
                   Phi = (I-B)^-1 Psi (I-B)^-T
  2. COMPOSITE model-implied matris kullanılır.
     Bir yapının kendi göstergeleri arasındaki korelasyonlar SERBESTTİR
     (blok içi doygun). Sadece BLOKLAR ARASI korelasyonlar kısıtlıdır:
         sigma_ij = lambda_i * phi_kl * lambda_j
     JS sürümü blok içinde lambda_i*lambda_j kullanıyordu; bu ortak faktör
     (common factor) varsayımıdır, composite model değil.
  3. d_G literatürdeki GEODEZİK uzaklıkla hesaplanır:
         d_G = (1/2) * sum( ln(eigenvalue_i(S^-1 * Sigma))^2 )
     JS sürümü tek tek korelasyonların log oranını alıyordu; farklı bir büyüklük.
  4. ÇIKARIM: bootstrap tabanlı exact-fit testi.
     Veri, Sigma'ya uyacak biçimde dönüştürülür, oradan yeniden örneklenir,
     her örnekte model yeniden tahmin edilip uzaklık hesaplanır.
     HI95 = %95 yüzdelik. Gözlenen uzaklık HI95'in altındaysa model reddedilmez.
     Uydurma 0.5 / 1.5 eşikleri YOKTUR.

Kullanım (plssem.py içinden):

    from fit_indices import compute_fit_indices

    fit = compute_fit_indices(
        df=df,                         # ham veri (pandas DataFrame)
        constructs=constructs,         # [{"name": "PU", "items": ["PU1", ...]}, ...]
        hypotheses=hypotheses,         # [{"from": "PEOU", "to": "PU"}, ...]
        loadings=loadings,             # [{"construct": "PU", "item": "PU1", "loading": 0.83}, ...]
        bootstrap_samples=500,
        seed=42,
    )
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any, Callable, Dict, List, Optional, Sequence


# ══════════════════════════════════════════════════════════════════
#  Yardımcılar
# ══════════════════════════════════════════════════════════════════

def _corr(mat: np.ndarray) -> np.ndarray:
    """Sütunlar arası Pearson korelasyon matrisi (NaN'lar sütun ortalamasıyla dolu)."""
    c = np.corrcoef(mat, rowvar=False)
    c = np.atleast_2d(c)
    # Sayısal güvenlik
    c = np.nan_to_num(c, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(c, 1.0)
    return (c + c.T) / 2.0


def _psd_sqrt(A: np.ndarray) -> np.ndarray:
    """Simetrik matrisin karekökü (negatif özdeğerler sıfıra kırpılır)."""
    w, V = np.linalg.eigh((A + A.T) / 2.0)
    w = np.clip(w, 1e-12, None)
    return V @ np.diag(np.sqrt(w)) @ V.T


def _psd_inv_sqrt(A: np.ndarray) -> np.ndarray:
    """Simetrik matrisin ters karekökü."""
    w, V = np.linalg.eigh((A + A.T) / 2.0)
    w = np.clip(w, 1e-12, None)
    return V @ np.diag(1.0 / np.sqrt(w)) @ V.T


def _fill_na_with_mean(X: np.ndarray) -> np.ndarray:
    """Eksik değerleri sütun ortalamasıyla doldurur."""
    X = X.astype(float, copy=True)
    for j in range(X.shape[1]):
        col = X[:, j]
        m = np.isnan(col)
        if m.any():
            mu = np.nanmean(col)
            col[m] = 0.0 if np.isnan(mu) else mu
    return X


# ══════════════════════════════════════════════════════════════════
#  Model-implied korelasyon matrisi (COMPOSITE model)
# ══════════════════════════════════════════════════════════════════

def _model_implied_sigma(
    S: np.ndarray,
    blocks: List[List[int]],
    lam: np.ndarray,
    phi: np.ndarray,
) -> np.ndarray:
    """
    Composite model-implied korelasyon matrisi.

    Blok İÇİ  : gözlenen korelasyonlar aynen korunur (serbest / doygun).
    Bloklar ARASI: sigma_ij = lambda_i * phi_kl * lambda_j

    S     : gözlenen korelasyon matrisi (p x p)
    blocks: her yapının gösterge indeksleri
    lam   : her göstergenin dış yükü (p,)
    phi   : yapılar arası korelasyon matrisi (k x k)
    """
    p = S.shape[0]

    # ── VEKTOREL: gosterge -> blok esleme dizisi ──
    # Eski surumde dortlu ic ice Python dongusu vardi (O(p^2) yorumlayici islem);
    # bootstrap'ta yuzlerce kez cagrildigi icin ana darbogazdi.
    blk = np.empty(p, dtype=int)
    for k, bk in enumerate(blocks):
        blk[list(bk)] = k

    # Bloklar arasi: sigma_ij = lam_i * phi[blk_i, blk_j] * lam_j
    Sigma = np.outer(lam, lam) * phi[np.ix_(blk, blk)]

    # Blok ici: gozlenen korelasyonlar aynen korunur (composite model)
    same = blk[:, None] == blk[None, :]
    Sigma = np.where(same, S, Sigma)

    np.fill_diagonal(Sigma, 1.0)
    return (Sigma + Sigma.T) / 2.0


def _structural_phi(
    phi_obs: np.ndarray,
    names: List[str],
    hypotheses: Sequence[Dict[str, Any]],
) -> np.ndarray:
    """
    ESTIMATED model için yapılar arası korelasyon matrisi.

    Yol modeli:  eta = B eta + zeta
    Implied  :   Phi = (I-B)^-1 Psi (I-B)^-T

    B    : standartlaştırılmış yol katsayıları (satır = bağımlı, sütun = bağımsız)
    Psi  : artık kovaryans matrisi
             - dışsal yapılar : gözlenen aralarındaki korelasyonlar (serbest)
             - içsel yapılar  : 1 - R^2 köşegende, çapraz artıklar 0

    Yol katsayıları gözlenen Phi üzerinden OLS ile çözülür.
    """
    k = len(names)
    idx = {n: i for i, n in enumerate(names)}

    # Hangi yapıya hangi öncüller gidiyor
    preds: Dict[int, List[int]] = {i: [] for i in range(k)}
    for h in hypotheses:
        f = h.get("from") or h.get("from_")
        t = h.get("to")
        if f is None or t is None:
            continue
        f, t = str(f), str(t)
        # Etkileşim terimleri (A_x_B) yapı düğümü değildir
        if "_x_" in f or "_x_" in t:
            continue
        if f not in idx or t not in idx:
            continue
        if idx[f] not in preds[idx[t]]:
            preds[idx[t]].append(idx[f])

    B = np.zeros((k, k))
    r2 = np.zeros(k)

    for t in range(k):
        xs = preds[t]
        if not xs:
            continue
        Sxx = phi_obs[np.ix_(xs, xs)]
        Sxy = phi_obs[np.ix_(xs, [t])].ravel()
        try:
            beta = np.linalg.solve(Sxx, Sxy)
        except np.linalg.LinAlgError:
            beta = np.linalg.pinv(Sxx) @ Sxy
        B[t, xs] = beta
        r2[t] = float(np.clip(beta @ Sxy, 0.0, 1.0))

    endog = np.array([len(preds[i]) > 0 for i in range(k)])

    # Psi
    Psi = np.zeros((k, k))
    exog_idx = np.where(~endog)[0]
    if exog_idx.size:
        Psi[np.ix_(exog_idx, exog_idx)] = phi_obs[np.ix_(exog_idx, exog_idx)]
    for i in np.where(endog)[0]:
        Psi[i, i] = max(1.0 - r2[i], 1e-8)

    I = np.eye(k)
    try:
        A = np.linalg.inv(I - B)
    except np.linalg.LinAlgError:
        A = np.linalg.pinv(I - B)

    Phi = A @ Psi @ A.T

    # Köşegeni 1'e normalize et (korelasyon matrisi)
    d = np.sqrt(np.clip(np.diag(Phi), 1e-12, None))
    Phi = Phi / np.outer(d, d)
    np.fill_diagonal(Phi, 1.0)
    return (Phi + Phi.T) / 2.0


# ══════════════════════════════════════════════════════════════════
#  Uzaklık ölçüleri
# ══════════════════════════════════════════════════════════════════

def _srmr(S: np.ndarray, Sigma: np.ndarray) -> float:
    """
    Standardized Root Mean Square Residual.
    Korelasyon matrisinde köşegen her iki tarafta da 1 olduğu için
    yalnızca köşegen dışı artıklar üzerinden hesaplanır.
    """
    p = S.shape[0]
    iu = np.triu_indices(p, k=1)
    resid = S[iu] - Sigma[iu]
    return float(np.sqrt(np.mean(resid ** 2)))


def _d_uls(S: np.ndarray, Sigma: np.ndarray) -> float:
    """Unweighted Least Squares uzaklığı = köşegen dışı kare farklar toplamı."""
    p = S.shape[0]
    iu = np.triu_indices(p, k=1)
    resid = S[iu] - Sigma[iu]
    return float(np.sum(resid ** 2))


def _d_g(S: np.ndarray, Sigma: np.ndarray) -> float:
    """
    Geodezik uzaklık (Dijkstra & Henseler, 2015):
        d_G = (1/2) * sum_i ( ln(lambda_i) )^2
    lambda_i : S^-1 * Sigma matrisinin özdeğerleri
    """
    try:
        S_inv_sqrt = _psd_inv_sqrt(S)
        M = S_inv_sqrt @ Sigma @ S_inv_sqrt   # simetrik, S^-1*Sigma ile aynı özdeğerler
        w = np.linalg.eigvalsh((M + M.T) / 2.0)
        w = np.clip(w, 1e-10, None)
        return float(0.5 * np.sum(np.log(w) ** 2))
    except Exception:
        return float("nan")


# ══════════════════════════════════════════════════════════════════
#  Varsayılan tahminci (korelasyon tabanlı — plssem.py ile uyumlu)
# ══════════════════════════════════════════════════════════════════

def _default_estimator(X: np.ndarray, blocks: List[List[int]]):
    """
    Kompozit skorları eşit ağırlıkla kurar, yükleri gösterge-skor korelasyonu
    olarak alır. Mevcut motorunuzun mantığıyla aynıdır.

    plssem.py'de gerçek PLS ağırlıkları hesaplanıyorsa, compute_fit_indices'e
    estimator=... ile kendi fonksiyonunuzu geçirin; imza aynıdır.

    Döner: (lam (p,), phi (k,k), scores (n,k))
    """
    n, p = X.shape
    Z = (X - X.mean(axis=0)) / np.clip(X.std(axis=0, ddof=1), 1e-12, None)

    k = len(blocks)
    scores = np.zeros((n, k))
    for kk, b in enumerate(blocks):
        s = Z[:, b].mean(axis=1)
        sd = s.std(ddof=1)
        scores[:, kk] = (s - s.mean()) / (sd if sd > 1e-12 else 1.0)

    lam = np.zeros(p)
    for kk, b in enumerate(blocks):
        for i in b:
            v = np.corrcoef(Z[:, i], scores[:, kk])[0, 1]
            lam[i] = 0.0 if np.isnan(v) else v

    phi = _corr(scores)
    return lam, phi, scores


# ══════════════════════════════════════════════════════════════════
#  Ana fonksiyon
# ══════════════════════════════════════════════════════════════════

def compute_fit_indices(
    df: pd.DataFrame,
    constructs: Sequence[Dict[str, Any]],
    hypotheses: Sequence[Dict[str, Any]],
    loadings: Optional[Sequence[Dict[str, Any]]] = None,
    bootstrap_samples: int = 500,
    seed: Optional[int] = 42,
    estimator: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Saturated ve estimated modeller için SRMR, d_ULS, d_G ile
    bootstrap tabanlı HI95 / p değerlerini ve NFI'yı hesaplar.

    bootstrap_samples <= 0 verilirse çıkarım atlanır (sadece değerler döner).
    """
    rng = np.random.default_rng(seed)

    # ── Blokları kur ────────────────────────────────────────────
    names: List[str] = []
    blocks: List[List[int]] = []
    items: List[str] = []
    for c in constructs:
        cname = str(c.get("name"))
        cols = [it for it in c.get("items", []) if it in df.columns]
        if len(cols) < 2:
            continue
        names.append(cname)
        blocks.append([len(items) + i for i in range(len(cols))])
        items.extend(cols)

    if len(names) < 2 or len(items) < 4:
        return {"ok": False, "error": "Uyum indeksleri için en az 2 yapı ve 4 gösterge gerekir."}

    X = _fill_na_with_mean(df[items].to_numpy(dtype=float))
    n, p = X.shape
    if n < 10:
        return {"ok": False, "error": "Örneklem çok küçük."}

    est = estimator or _default_estimator
    S = _corr(X)

    # ── Model tahmini ───────────────────────────────────────────
    lam, phi_obs, _scores = est(X, blocks)

    # Dışarıdan yük verildiyse onu kullan (motorun kendi yükleriyle tutarlılık)
    if loadings:
        lmap = {str(l.get("item")): float(l.get("loading", 0) or 0) for l in loadings}
        lam = np.array([lmap.get(it, lam[i]) for i, it in enumerate(items)], dtype=float)

    phi_str = _structural_phi(phi_obs, names, hypotheses)

    Sigma_sat = _model_implied_sigma(S, blocks, lam, phi_obs)
    Sigma_est = _model_implied_sigma(S, blocks, lam, phi_str)

    obs = {
        "saturated": {
            "SRMR": _srmr(S, Sigma_sat),
            "d_ULS": _d_uls(S, Sigma_sat),
            "d_G": _d_g(S, Sigma_sat),
        },
        "estimated": {
            "SRMR": _srmr(S, Sigma_est),
            "d_ULS": _d_uls(S, Sigma_est),
            "d_G": _d_g(S, Sigma_est),
        },
    }

    # ── NFI  (null model: bloklar arası tüm korelasyonlar 0) ────
    Sigma_null = np.eye(p)
    for b in blocks:
        Sigma_null[np.ix_(b, b)] = S[np.ix_(b, b)]
    d_null = _d_uls(S, Sigma_null)
    nfi = (1.0 - obs["estimated"]["d_ULS"] / d_null) if d_null > 1e-12 else None

    result: Dict[str, Any] = {
        "ok": True,
        "n": int(n),
        "p_indicators": int(p),
        "k_constructs": int(len(names)),
        "saturated": obs["saturated"],
        "estimated": obs["estimated"],
        "NFI": None if nfi is None else float(nfi),
        "bootstrap_samples": 0,
        "inference": None,
        "note": (
            "Composite model-implied korelasyon matrisi kullanildi (blok ici serbest). "
            "d_G geodezik uzaklik olarak ozdegerlerden hesaplandi."
        ),
    }

    if bootstrap_samples and bootstrap_samples > 0:
        result["inference"] = _bootstrap_inference(
            X, blocks, S, Sigma_sat, Sigma_est, obs, est, names,
            hypotheses, int(bootstrap_samples), rng,
        )
        result["bootstrap_samples"] = int(bootstrap_samples)

    return result


# ══════════════════════════════════════════════════════════════════
#  Bootstrap tabanlı exact-fit testi
# ══════════════════════════════════════════════════════════════════

def _bootstrap_inference(
    X, blocks, S, Sigma_sat, Sigma_est, obs, est, names,
    hypotheses, B, rng,
) -> Dict[str, Any]:
    """
    Henseler vd. (2016) exact-fit testi.

    1) Veri, model-implied Sigma'ya uyacak sekilde donusturulur:
           X* = X . S^(-1/2) . Sigma^(1/2)
       Boylece H0 (model dogru) altinda bir populasyon elde edilir.
    2) X* uzerinden satir yeniden ornekleme yapilir.
    3) Her ornekte model YENIDEN tahmin edilir, uzaklik hesaplanir.
    4) HI95 = %95 yuzdelik. p = P(bootstrap uzakligi >= gozlenen).

    Gozlenen uzaklik HI95'in ALTINDAYSA model reddedilmez.
    """
    n, p = X.shape
    Z = (X - X.mean(axis=0)) / np.clip(X.std(axis=0, ddof=1), 1e-12, None)
    S_inv_sqrt = _psd_inv_sqrt(S)

    out: Dict[str, Any] = {}

    for model_key, Sigma in (("saturated", Sigma_sat), ("estimated", Sigma_est)):
        T = Z @ S_inv_sqrt @ _psd_sqrt(Sigma)   # H0 populasyonu

        dist = {"SRMR": [], "d_ULS": [], "d_G": []}
        for _ in range(B):
            idx = rng.integers(0, n, size=n)
            Xb = T[idx, :]
            if np.any(Xb.std(axis=0, ddof=1) < 1e-10):
                continue
            try:
                Sb = _corr(Xb)
                lam_b, phi_b, _ = est(Xb, blocks)
                if model_key == "estimated":
                    phi_b = _structural_phi(phi_b, names, hypotheses)
                Sigma_b = _model_implied_sigma(Sb, blocks, lam_b, phi_b)
                dist["SRMR"].append(_srmr(Sb, Sigma_b))
                dist["d_ULS"].append(_d_uls(Sb, Sigma_b))
                dg = _d_g(Sb, Sigma_b)
                if np.isfinite(dg):
                    dist["d_G"].append(dg)
            except Exception:
                continue

        res = {}
        for metric in ("SRMR", "d_ULS", "d_G"):
            arr = np.array(dist[metric], dtype=float)
            arr = arr[np.isfinite(arr)]
            o = obs[model_key][metric]
            if arr.size < 20 or not np.isfinite(o):
                res[metric] = {"HI95": None, "HI99": None, "p_value": None, "verdict": None}
                continue
            hi95 = float(np.percentile(arr, 95))
            hi99 = float(np.percentile(arr, 99))
            pval = float(np.mean(arr >= o))
            res[metric] = {
                "HI95": hi95,
                "HI99": hi99,
                "p_value": pval,
                # p > 0.05  ⇒  model reddedilmez
                "verdict": "not rejected" if pval > 0.05 else "rejected",
                "n_valid": int(arr.size),
            }
        out[model_key] = res

    return out
