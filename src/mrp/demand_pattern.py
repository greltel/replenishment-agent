"""
Demand pattern of a material and the inventory policy that goes with it
(DEMAND_POLICY=pattern).

Why
───
Spare-parts demand is mostly not continuous. In the case company's data
(50,160 active materials, the 52 weeks up to 06.02.2026) only 710
materials sell in most weeks (44 % of the sales value); 10,365 sell in
some weeks (50 %), 10,558 in at most two weeks (7 %) and 28,527 not at
all. The legacy policy treats every material
as continuous demand: a moving-average forecast and SS = z·σ·√LT, with the
mean and σ taken over the days between the first and the last sale — one
unit sold once a year becomes "one unit a day" and a safety stock of about
six units.

Steps for one material at the as-of date t
──────────────────────────────────────────
1. Demand window: the 364 days (t−363 … t) of consumption (the demand
   movement types), as daily quantities and as 52 weeks ending at t
   (week 52 = days t−6 … t). Zero days and zero weeks are part of it.

2. Classification (Syntetos, Boylan & Croston 2005), on the weekly series:
       ADI = 52 / n_demand_weeks         average inter-demand interval (weeks)
       CV² = (s / x̄)²  of the non-zero weekly quantities (sample std)
   ┌──────────────┬──────────────────────────────────────────────┐
   │ NONE         │ no demand in the 52 weeks                    │
   │ RARE         │ demand in 1–2 weeks (≤ RARE_MAX_DEMAND_WEEKS)│
   │ SMOOTH       │ ADI < 1.32, CV² < 0.49                       │
   │ ERRATIC      │ ADI < 1.32, CV² ≥ 0.49                       │
   │ INTERMITTENT │ ADI ≥ 1.32, CV² < 0.49                       │
   │ LUMPY        │ ADI ≥ 1.32, CV² ≥ 0.49                       │
   └──────────────┴──────────────────────────────────────────────┘
   The cut-offs come from comparing the mean square error of the methods;
   the scheme was validated on 3,000 intermittent series of the automotive
   industry, and assessed for stock control on ~16,000 SKUs by Boylan,
   Syntetos & Karakostas (2008). RARE is an addition to the scheme: with
   one or two demand weeks there is no interval or variability to estimate.

3. Forecast: SMOOTH / ERRATIC → the agent's method (moving average);
   INTERMITTENT / LUMPY → SBA, Croston's method with the Syntetos–Boylan
   bias correction (src.utils.forecasting.sba); RARE / NONE → 0.

4. Safety stock for the cycle service level α (the agent's desire, 98 %):
   • SMOOTH / ERRATIC:  SS = z_α · σ_d · √LT, σ_d the standard deviation of
     the 364 daily quantities (zero days included).
   • INTERMITTENT / LUMPY: the lead-time demand is compound Poisson — the
     number of demand weeks within the lead time is Poisson with mean
     λ = p · LT/7 (p = n_demand_weeks / 52) and each one brings a quantity
     drawn from the observed non-zero weekly quantities (Feeney &
     Sherbrooke 1966; Silver, Pyke & Peterson 1998). The reorder level s*
     is the smallest s with P(LTD ≤ s) ≥ α, and SS = max(s* − E[LTD], 0),
     E[LTD] = λ · x̄. The normal formula would assume a demand that does
     not exist on most days.
   • RARE / NONE: no safety stock — the material is bought to order.
   A safety stock maintained in SAP (MARC-EISBE) always wins.

5. Expedite (rule R-EXPEDITE): never for RARE / NONE; for INTERMITTENT /
   LUMPY only when a demand within the lead time is more likely than not,
   P = 1 − e^(−λ) ≥ EXPEDITE_MIN_DEMAND_PROBABILITY. A part that sells one
   week in ten is not worth an express shipment because its stock is zero.

References
──────────
Boylan, J.E., Syntetos, A.A. & Karakostas, G.C. (2008). Classification for
  forecasting and stock control: a case study. Journal of the Operational
  Research Society 59(4), 473–481. doi:10.1057/palgrave.jors.2602312
Croston, J.D. (1972). Forecasting and stock control for intermittent
  demands. Operational Research Quarterly 23(3), 289–303.
  doi:10.1057/jors.1972.50
Feeney, G.J. & Sherbrooke, C.C. (1966). The (S−1, S) inventory policy
  under compound Poisson demand. Management Science 12(5), 391–411.
  doi:10.1287/mnsc.12.5.391
Silver, E.A., Pyke, D.F. & Peterson, R. (1998). Inventory Management and
  Production Planning and Scheduling, 3rd ed. Wiley.
Syntetos, A.A. & Boylan, J.E. (2005). The accuracy of intermittent demand
  estimates. International Journal of Forecasting 21(2), 303–314.
  doi:10.1016/j.ijforecast.2004.10.001
Syntetos, A.A., Boylan, J.E. & Croston, J.D. (2005). On the categorization
  of demand patterns. Journal of the Operational Research Society 56(5),
  495–503. doi:10.1057/palgrave.jors.2601841
Teunter, R.H., Syntetos, A.A. & Babai, M.Z. (2011). Intermittent demand:
  linking forecasting to inventory obsolescence. European Journal of
  Operational Research 214(3), 606–615. doi:10.1016/j.ejor.2011.05.018
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# ── Parameters ──────────────────────────────────────────────────────────
HISTORY_WEEKS = 52
HISTORY_DAYS = HISTORY_WEEKS * 7          # 364
ADI_CUTOFF = 1.32                         # Syntetos, Boylan & Croston (2005)
CV2_CUTOFF = 0.49
RARE_MAX_DEMAND_WEEKS = 2
EXPEDITE_MIN_DEMAND_PROBABILITY = 0.5
# Compound Poisson: beyond these sizes the normal approximation of the
# compound distribution is used (mean λ·x̄, variance λ·E[X²])
_MAX_POISSON_RATE = 30.0
_MAX_GRID = 200_000

NONE, RARE = "NONE", "RARE"
SMOOTH, ERRATIC = "SMOOTH", "ERRATIC"
INTERMITTENT, LUMPY = "INTERMITTENT", "LUMPY"
PATTERNS = (SMOOTH, ERRATIC, INTERMITTENT, LUMPY, RARE, NONE)
CONTINUOUS_PATTERNS = (SMOOTH, ERRATIC)
SPORADIC_PATTERNS = (INTERMITTENT, LUMPY)
TO_ORDER_PATTERNS = (RARE, NONE)          # bought to order, no stock kept

# Greek labels for reports and the dashboard
PATTERN_LABELS = {
    SMOOTH: "Σταθερή", ERRATIC: "Ακανόνιστη", INTERMITTENT: "Διακοπτόμενη",
    LUMPY: "Διακοπτόμενη-ακανόνιστη", RARE: "Σπάνια", NONE: "Χωρίς ζήτηση",
}


@dataclass
class DemandProfile:
    """Demand of one material over the 52 weeks ending at the as-of date."""
    pattern: str
    n_demand_weeks: int = 0
    adi: float | None = None              # weeks
    cv2: float | None = None
    week_share: float = 0.0               # p = n_demand_weeks / 52
    mean_size: float = 0.0                # x̄ of the non-zero weekly quantities
    daily_mean: float = 0.0
    daily_std: float = 0.0                # σ_d over the 364 days, zero days included
    sizes: list[float] = field(default_factory=list)
    weekly: list[float] = field(default_factory=list)   # oldest → newest

    def demand_probability(self, lead_time_days: float) -> float:
        """P(at least one demand week within the lead time) = 1 − e^(−λ)."""
        lam = self.week_share * max(float(lead_time_days or 0), 0.0) / 7.0
        return 1.0 - math.exp(-lam)


# ── 1. Demand window ────────────────────────────────────────────────────
def daily_window(posting_dates: Iterable[date], quantities: Iterable[float],
                 as_of: date) -> np.ndarray:
    """The 364 daily demand quantities t−363 … t (oldest first), from the
    consumption movements (quantities taken as absolute values). Movements
    outside the window are ignored."""
    daily = np.zeros(HISTORY_DAYS)
    for d, q in zip(posting_dates, quantities):
        age = (as_of - d).days
        if 0 <= age < HISTORY_DAYS:
            daily[HISTORY_DAYS - 1 - age] += abs(float(q))
    return daily


def profile_from_movements(movements: Sequence, as_of: date) -> DemandProfile:
    """Profile from Movement objects (.posting_date, .quantity)."""
    daily = daily_window((m.posting_date for m in movements),
                         (m.quantity for m in movements), as_of)
    return profile_from_daily(daily)


def profiles_from_frame(df: pd.DataFrame, as_of: date,
                        material_ids: Iterable[str] | None = None) -> dict[str, DemandProfile]:
    """Profiles for many materials from a DataFrame of consumption movements
    [material_id, posting_date, quantity] — the same numbers as
    profile_from_movements. Materials without a row get the NONE profile."""
    out: dict[str, DemandProfile] = {}
    if not df.empty:
        dates = pd.to_datetime(df["posting_date"]).dt.date
        ages = np.array([(as_of - d).days for d in dates])
        keep = (ages >= 0) & (ages < HISTORY_DAYS)
        sub = pd.DataFrame({"material_id": df["material_id"].values[keep],
                            "pos": HISTORY_DAYS - 1 - ages[keep],
                            "qty": np.abs(df["quantity"].astype(float).values[keep])})
        for mid, grp in sub.groupby("material_id"):
            daily = np.zeros(HISTORY_DAYS)
            np.add.at(daily, grp["pos"].values, grp["qty"].values)
            out[mid] = profile_from_daily(daily)
    if material_ids is not None:
        empty = None
        for mid in material_ids:
            if mid not in out:
                empty = empty or profile_from_daily(np.zeros(HISTORY_DAYS))
                out[mid] = empty
    return out


# ── 2. Classification ───────────────────────────────────────────────────
def profile_from_daily(daily: np.ndarray) -> DemandProfile:
    """Classify a 364-day demand window (see the module docstring)."""
    daily = np.asarray(daily, dtype=float)
    weekly = daily.reshape(HISTORY_WEEKS, 7).sum(axis=1)
    sizes = weekly[weekly > 0]
    n = int(sizes.size)
    base = dict(n_demand_weeks=n, week_share=n / HISTORY_WEEKS,
                daily_mean=float(daily.mean()), daily_std=float(daily.std(ddof=0)),
                sizes=[float(x) for x in sizes], weekly=[float(x) for x in weekly])
    if n == 0:
        return DemandProfile(pattern=NONE, **base)
    mean_size = float(sizes.mean())
    adi = HISTORY_WEEKS / n
    cv2 = float((sizes.std(ddof=1) / mean_size) ** 2) if n > 1 else None
    base.update(mean_size=mean_size, adi=adi, cv2=cv2)
    if n <= RARE_MAX_DEMAND_WEEKS:
        return DemandProfile(pattern=RARE, **base)
    if adi < ADI_CUTOFF:
        pattern = SMOOTH if cv2 < CV2_CUTOFF else ERRATIC
    else:
        pattern = INTERMITTENT if cv2 < CV2_CUTOFF else LUMPY
    return DemandProfile(pattern=pattern, **base)


# ── 3. Forecast method ──────────────────────────────────────────────────
def forecast_method_for(pattern: str, default: str = "moving_average") -> str | None:
    """Forecasting method per pattern; None = no forecast (zero demand)."""
    if pattern in CONTINUOUS_PATTERNS:
        return default
    if pattern in SPORADIC_PATTERNS:
        return "sba"
    return None


# ── 4. Safety stock ─────────────────────────────────────────────────────
def z_value(service_level: float) -> float:
    """One-sided standard normal quantile z_α."""
    return NormalDist().inv_cdf(service_level)


def compound_poisson_quantile(rate: float, sizes: Sequence[float],
                              service_level: float) -> float:
    """Smallest s with P(D ≤ s) ≥ α for D = X₁ + … + X_N, N ~ Poisson(rate)
    and X_i drawn from the observed quantities `sizes` (rounded up to whole
    units: spare parts are counted in pieces).

    Exact on the integer grid: P(D = d) = Σ_k Pois(k; rate) · P(S_k = d),
    S_k the k-fold convolution of the size distribution, summed until the
    Poisson tail is below 1e-9. For very large rates or quantities the
    normal approximation with mean rate·x̄ and variance rate·E[X²] is used.
    """
    x = np.ceil(np.asarray(sizes, dtype=float) - 1e-9).astype(int)
    x = x[x > 0]
    if rate <= 0 or x.size == 0:
        return 0.0
    if rate > _MAX_POISSON_RATE or x.max() * (rate + 6 * math.sqrt(rate) + 1) > _MAX_GRID:
        mean = rate * x.mean()
        sd = math.sqrt(rate * float((x.astype(float) ** 2).mean()))
        return float(math.ceil(mean + z_value(service_level) * sd))
    f = np.bincount(x) / x.size                 # P(X = j), f[0] = 0
    pk = math.exp(-rate)                        # P(N = 0)
    pmf = np.array([pk])                        # P(D = d)
    conv = np.array([1.0])                      # P(S_0 = d)
    cum, k = pk, 0
    while 1.0 - cum > 1e-9 and k < 200:
        k += 1
        conv = np.convolve(conv, f)
        pk *= rate / k
        cum += pk
        if conv.size > pmf.size:
            pmf = np.pad(pmf, (0, conv.size - pmf.size))
        pmf[:conv.size] += pk * conv
    cdf = np.cumsum(pmf)
    idx = int(np.searchsorted(cdf, service_level - 1e-12))
    return float(min(idx, cdf.size - 1))


def safety_stock_for(profile: DemandProfile, lead_time_days: float,
                     service_level: float) -> float:
    """Safety stock of the pattern (step 4 of the module docstring)."""
    lt = max(float(lead_time_days or 0), 0.0)
    if lt <= 0 or profile.pattern in TO_ORDER_PATTERNS:
        return 0.0
    if profile.pattern in CONTINUOUS_PATTERNS:
        return round(z_value(service_level) * profile.daily_std * math.sqrt(lt), 2)
    rate = profile.week_share * lt / 7.0
    reorder_level = compound_poisson_quantile(rate, profile.sizes, service_level)
    return round(max(reorder_level - rate * profile.mean_size, 0.0), 2)


def expedite_allowed(pattern: str | None, demand_probability: float) -> bool:
    """Step 5: may R-EXPEDITE flag an order of this material?"""
    if pattern is None or pattern in CONTINUOUS_PATTERNS:
        return True
    if pattern in TO_ORDER_PATTERNS:
        return False
    return demand_probability >= EXPEDITE_MIN_DEMAND_PROBABILITY
