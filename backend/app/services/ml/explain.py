from __future__ import annotations

from typing import List, Dict

import numpy as np
import pandas as pd

try:
    import shap
except Exception:  # pragma: no cover
    shap = None


def top_k_drivers(model, X: pd.DataFrame, k: int = 5) -> List[Dict]:
    # Try SHAP TreeExplainer first
    if shap is not None:
        try:
            explainer = shap.TreeExplainer(model)
            sample = X.sample(n=min(100, len(X)), random_state=0) if len(X) > 0 else X
            shap_vals = explainer.shap_values(sample)
            mean_abs = np.mean(np.abs(shap_vals), axis=0)
            idx = np.argsort(mean_abs)[::-1][:k]
            feats = list(X.columns)
            return [{"feature": feats[i], "shap": round(float(mean_abs[i]), 6)} for i in idx]
        except Exception:
            pass  # Fall through to feature_importances_ fallback

    # Fallback to feature importances (works for XGBoost, GBR, RandomForest, etc.)
    if hasattr(model, "feature_importances_"):
        imps = model.feature_importances_
        names = list(X.columns)
        idx = np.argsort(imps)[::-1][:k]
        return [{"feature": names[i], "shap": round(float(imps[i]), 6)} for i in idx]

    return [{"feature": c, "shap": 0.0} for c in X.columns[:k]]
