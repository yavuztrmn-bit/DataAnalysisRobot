import pandas as pd
import numpy as np
from semopy import Model
try:
    from semopy import calc_stats
except ImportError:
    calc_stats = None


def _safe_float(val):
    """NaN/inf'i None'a çevir (JSON serializable)."""
    if val is None:
        return None
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _compute_fit_indices(model):
    """
    semopy.calc_stats ile fit indeksleri hesapla.
    Hata olursa boş dict döner.
    """
    if calc_stats is None:
        return {
            "available": False,
            "error": "semopy.calc_stats not available (upgrade semopy).",
        }

    try:
        stats_df = calc_stats(model)
        # calc_stats DataFrame döner, tek satır
        # Sütunlar semopy sürümüne göre değişebilir
        row = stats_df.iloc[0] if len(stats_df) > 0 else None
        if row is None:
            return {"available": False, "error": "calc_stats returned empty"}

        # Sütun adlarını normalize et (semopy sürüm farkları için)
        cols_lower = {c.lower(): c for c in stats_df.columns}

        def get(*names):
            """İlk bulunan sütunu döner."""
            for n in names:
                key = n.lower()
                if key in cols_lower:
                    return row[cols_lower[key]]
            return None

        # χ² ve DoF
        chi2 = get("chi2", "chi-square", "chisquare")
        dof = get("dof", "df", "degrees of freedom")
        chi2_pvalue = get("chi2 p-value", "p-value", "pvalue", "p_value")

        # χ²/dof
        chi2_dof_ratio = None
        if chi2 is not None and dof is not None and dof != 0:
            try:
                chi2_dof_ratio = float(chi2) / float(dof)
            except Exception:
                pass

        # Diğer indices
        cfi = get("cfi")
        tli = get("tli", "nnfi")
        rmsea = get("rmsea")
        srmr = get("srmr")
        gfi = get("gfi")
        agfi = get("agfi")
        nfi = get("nfi")
        aic = get("aic")
        bic = get("bic")

        return {
            "available": True,
            "chi2": _safe_float(chi2),
            "dof": _safe_float(dof),
            "chi2_pvalue": _safe_float(chi2_pvalue),
            "chi2_dof_ratio": _safe_float(chi2_dof_ratio),
            "cfi": _safe_float(cfi),
            "tli": _safe_float(tli),
            "rmsea": _safe_float(rmsea),
            "srmr": _safe_float(srmr),
            "gfi": _safe_float(gfi),
            "agfi": _safe_float(agfi),
            "nfi": _safe_float(nfi),
            "aic": _safe_float(aic),
            "bic": _safe_float(bic),
        }
    except Exception as e:
        return {
            "available": False,
            "error": f"Fit indices calculation failed: {str(e)[:120]}",
        }


def _compute_construct_correlations(model, construct_names):
    """
    CFA sonrası yapılar arası (latent) korelasyonları hesapla.
    Backend'de FL/HTMT matrisi için kullanılabilir.
    """
    try:
        est = model.inspect(std_est=True)
        # Latent covariances "~~" operator ile gelir
        # Standardize edildiğinde bunlar korelasyonlara dönüşür
        corr_map = {}
        for _, row in est.iterrows():
            op = str(row.get("op", ""))
            lval = str(row.get("lval", ""))
            rval = str(row.get("rval", ""))
            std_val = row.get("Est. Std", row.get("Estimate", None))

            if op == "~~" and lval in construct_names and rval in construct_names:
                if std_val is not None:
                    v = float(std_val)
                    corr_map.setdefault(lval, {})[rval] = round(v, 4)
                    corr_map.setdefault(rval, {})[lval] = round(v, 4)
        # Köşegen = 1.0
        for cn in construct_names:
            corr_map.setdefault(cn, {})[cn] = 1.0
        return corr_map
    except Exception:
        return {}


def run_cfa(df: pd.DataFrame, constructs: list):
    constructs = [{"name": c["name"], "items": list(c["items"])} for c in constructs]
    needed_cols = []
    for c in constructs:
        needed_cols.extend(c["items"])
    needed_cols = list(dict.fromkeys(needed_cols))

    for col in needed_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df_model = df[needed_cols].copy()
    df_model = df_model.fillna(df_model.mean(numeric_only=True))
    df_model = df_model.dropna(axis=0, how="any")

    model_desc = "\n".join(
        f'{c["name"]} =~ ' + ' + '.join(c["items"])
        for c in constructs if c["items"]
    )

    model = Model(model_desc)
    model.fit(df_model)
    est = model.inspect(std_est=True)

    construct_names = [c["name"] for c in constructs]

    # ─── Loadings ───────────────────────────────
    loading_rows = []
    for _, row in est.iterrows():
        op = str(row.get("op", ""))
        lval = str(row.get("lval", ""))
        rval = str(row.get("rval", ""))
        std_val = row.get("Est. Std", row.get("Estimate", None))
        se_val = row.get("Std. Err", None)
        z_val = row.get("z-value", row.get("z_value", None))
        p_val = row.get("p-value", row.get("p_value", None))

        item = None
        construct = None
        if op == "~" and rval in construct_names:
            item = lval
            construct = rval
        elif op == "=~" and lval in construct_names:
            construct = lval
            item = rval

        if item is None or construct is None or std_val is None:
            continue

        val = float(std_val)
        loading_rows.append({
            "construct": construct,
            "item": item,
            "loading": round(val, 3),
            "se": _safe_float(se_val),
            "z": _safe_float(z_val),
            "p": _safe_float(p_val),
            "flag": "review" if val < 0.70 else ""
        })

    # ─── Loadings matrix ────────────────────────
    all_items = []
    for c in constructs:
        all_items.extend(c["items"])
    all_items = list(dict.fromkeys(all_items))

    matrix_rows = []
    for item in all_items:
        row_obj = {"Indicator": item}
        for cn in construct_names:
            row_obj[cn] = ""
        for lr in loading_rows:
            if lr["item"] == item:
                row_obj[lr["construct"]] = lr["loading"]
        matrix_rows.append(row_obj)

    # ─── Fit indices ────────────────────────────
    fit_indices = _compute_fit_indices(model)

    # ─── Construct correlations ─────────────────
    construct_corrs = _compute_construct_correlations(model, construct_names)

    # ─── Sample size ────────────────────────────
    n_obs = len(df_model)

    return {
        "ok": True,
        "n": n_obs,
        "model": model_desc,
        "loadings_long": loading_rows,
        "loadings_matrix": matrix_rows,
        "fit_indices": fit_indices,
        "construct_correlations": construct_corrs,
    }
