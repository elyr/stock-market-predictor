"""
Turning a ranked list into a portfolio.

The ranking says which assets look best; this module decides which of them to
hold and how much of each. Two simple, robust rules are applied:

* a sector cap, so the picks are not ten versions of the same bet, and
* inverse-volatility weights, so a very volatile asset does not dominate the
  portfolio's risk.
"""

from typing import Optional

import numpy as np
import pandas as pd


def select_portfolio(ranked: pd.DataFrame, top_n: int, score_col: str = 'Composite_Score',
                     sector_col: Optional[str] = 'Sector', vol_col: Optional[str] = 'Volatility',
                     max_per_sector: int = 0, weighting: str = 'equal') -> pd.DataFrame:
    """
    Pick the top ``top_n`` rows by score, respecting a per-sector cap, and weight them.

    Args:
        ranked: one row per asset
        top_n: number of positions
        score_col: column to rank by (higher is better)
        sector_col: sector column; ignored when missing or when max_per_sector is 0
        vol_col: volatility column for inverse-volatility weighting
        max_per_sector: maximum picks from one sector (0 = no cap); unknown sectors are not capped
        weighting: 'equal' or 'inverse_volatility'

    Returns:
        The selected rows, best first, with a ``Weight`` column summing to 1
    """
    if ranked.empty or top_n <= 0:
        return ranked.head(0).assign(Weight=pd.Series(dtype=float))

    ordered = ranked.sort_values(score_col, ascending=False, kind='stable')
    use_cap = max_per_sector > 0 and sector_col and sector_col in ordered.columns
    if use_cap:
        counts: dict = {}
        keep = []
        for idx, sector in ordered[sector_col].items():
            unknown = sector is None or (isinstance(sector, float) and np.isnan(sector)) or sector in ('', 'N/A')
            if not unknown and counts.get(sector, 0) >= max_per_sector:
                continue
            if not unknown:
                counts[sector] = counts.get(sector, 0) + 1
            keep.append(idx)
            if len(keep) == top_n:
                break
        selected = ordered.loc[keep].copy()
    else:
        selected = ordered.head(top_n).copy()

    if weighting == 'inverse_volatility' and vol_col and vol_col in selected.columns:
        vol = pd.to_numeric(selected[vol_col], errors='coerce')
        vol = vol.where(vol > 0).fillna(vol[vol > 0].median() if (vol > 0).any() else 1.0)
        inverse = 1.0 / vol
        selected['Weight'] = inverse / inverse.sum()
    else:
        selected['Weight'] = 1.0 / len(selected)
    return selected
