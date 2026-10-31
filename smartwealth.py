"""SmartWealth core engine: validation, allocation, projection, explainability."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

# ============================================================
# Constants / guardrails
# ============================================================
MAX_SINGLE_PRODUCT = 0.40
WEIGHT_TOL = 1e-6
RATE_FLOOR = -0.05
RATE_CAP = 0.20
SCENARIO_SPREAD = 0.03

# Horizon band → (cap on risk 4-5 combined, min weight in risk 1-2)
HORIZON_BANDS = [
    (36, 0.10, 0.70),
    (84, 0.30, 0.45),
    (10_000, 0.55, 0.25),
]

NUMERIC_FIELDS = [
    "goal_amount_inr", "horizon_months", "existing_investment_inr",
    "monthly_sip_inr", "risk_tolerance_score", "emergency_fund_months",
    "liquidity_need_inr",
]
REQUIRED_STRING_FIELDS = [
    "investor_id", "goal_label", "experience",
]


# ============================================================
# Data classes
# ============================================================
@dataclass
class ValidationResult:
    ok: bool
    profile: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Allocation:
    weights: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    fallback_used: bool = False


@dataclass
class Recommendation:
    investor_id: str
    allocations: dict[str, dict]        # product_id -> {weight, amount, name, ...}
    summary: dict                       # risk, cost, projections, warnings
    reasons: list[str]
    warnings: list[str]
    exceptions: list[str]


# ============================================================
# Validation
# ============================================================
def _coerce_float(name: str, value, errors: list[str]):
    """Try to convert to float. Appends to errors if invalid. Returns None if invalid."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        errors.append(f"Missing value for '{name}'.")
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        errors.append(f"Field '{name}' is not numeric: {value!r}.")
        return None
    if not math.isfinite(v):
        errors.append(f"Field '{name}' is not finite: {value!r}.")
        return None
    return v


def validate_profile(raw: dict) -> ValidationResult:
    res = ValidationResult(ok=True)
    prof: dict = {}

    # 1. String validation
    for f in REQUIRED_STRING_FIELDS:
        v = raw.get(f)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            res.errors.append(f"Missing required field '{f}'.")
        else:
            prof[f] = str(v).strip()

    # 2. Numeric parsing (accumulates ALL parse errors)
    parse_failed_fields = set()
    for f in NUMERIC_FIELDS:
        v = _coerce_float(f, raw.get(f), res.errors)
        if v is not None:
            prof[f] = v
        else:
            parse_failed_fields.add(f)

    prof["preference"] = str(raw.get("preference") or "").strip()

    # 3. Business logic checks — run on fields that parsed successfully,
    #    and also flag that we couldn't check the ones that failed to parse.
    if "goal_amount_inr" in prof and prof["goal_amount_inr"] <= 0:
        res.errors.append("Goal amount must be > 0.")
    if "existing_investment_inr" in prof and prof["existing_investment_inr"] < 0:
        res.errors.append("Existing investment cannot be negative.")
    if "monthly_sip_inr" in prof and prof["monthly_sip_inr"] < 0:
        res.errors.append("Monthly SIP cannot be negative.")
    if "liquidity_need_inr" in prof and prof["liquidity_need_inr"] < 0:
        res.errors.append("Liquidity need cannot be negative.")
    if "risk_tolerance_score" in prof and not (1 <= prof["risk_tolerance_score"] <= 5):
        res.errors.append("Risk tolerance must be between 1 and 5.")
    if "horizon_months" in prof and prof["horizon_months"] <= 0:
        res.errors.append("Horizon (months) must be > 0.")
    if "emergency_fund_months" in prof and prof["emergency_fund_months"] < 0:
        res.errors.append("Emergency fund months cannot be negative.")

    # Cross-field check only if both fields parsed
    if ("existing_investment_inr" in prof and "monthly_sip_inr" in prof
            and prof["existing_investment_inr"] == 0 and prof["monthly_sip_inr"] == 0):
        res.errors.append(
            "No investable capital: existing investment and monthly SIP are both zero."
        )

    # 4. Warnings — only when the field parsed correctly
    if "emergency_fund_months" in prof and prof["emergency_fund_months"] < 3:
        res.warnings.append(
            f"Emergency fund covers only {prof['emergency_fund_months']:.1f} months (< 3). "
            "Build a liquid buffer before committing capital to long-term goals."
        )
    if "horizon_months" in prof and prof["horizon_months"] <= 36:
        res.warnings.append(
            f"Short horizon ({prof['horizon_months']:.0f} months): high-risk products are restricted."
        )

    res.ok = len(res.errors) == 0
    res.profile = prof
    return res


def validate_products(products: list[dict]) -> list[str]:
    errors, seen = [], set()
    for p in products:
        pid = p.get("product_id")
        if not pid:
            errors.append("A product is missing 'product_id'.")
            continue
        if pid in seen:
            errors.append(f"Duplicate product_id: {pid}.")
        seen.add(pid)
        for f in ("risk_score", "assumed_annual_return", "annual_expense_ratio",
                  "liquidity_days", "minimum_investment_inr", "lock_in_months"):
            try:
                v = float(p.get(f))
                if not math.isfinite(v):
                    errors.append(f"Product {pid}: non-finite '{f}'.")
            except (TypeError, ValueError):
                errors.append(f"Product {pid}: invalid numeric field '{f}'.")
    return errors


def validate_allocation(weights: dict[str, float],
                        product_ids: Iterable[str]) -> list[str]:
    errs = []
    if not weights:
        return ["Allocation is empty."]
    for pid in weights:
        if pid not in product_ids:
            errs.append(f"Unknown product_id in allocation: {pid}.")
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOL:
        errs.append(f"Weights sum to {total:.6f}, expected 1.0 (±{WEIGHT_TOL}).")
    for pid, w in weights.items():
        if w < -WEIGHT_TOL:
            errs.append(f"Negative weight for {pid}: {w}.")
        if w > MAX_SINGLE_PRODUCT + WEIGHT_TOL:
            errs.append(f"{pid} weight {w:.3f} exceeds 40% cap.")
    return errs


# ============================================================
# Projection
# ============================================================
def future_value(P: float, S: float, r: float, n: int) -> float:
    """FV = P(1+r/12)^n + S[((1+r/12)^n - 1)/(r/12)]; linear when r≈0."""
    if n <= 0:
        return P
    if abs(r) < 1e-12:
        return P + S * n
    m = r / 12.0
    g = (1.0 + m) ** n
    fv = P * g + S * (g - 1.0) / m
    if not math.isfinite(fv):
        raise ValueError("Projection produced non-finite value.")
    return fv


def weighted_return(weights: dict[str, float],
                    by_id: dict[str, dict]) -> float:
    return sum(w * by_id[pid]["assumed_annual_return"] for pid, w in weights.items())


def scenario_range(P, S, r_port, n):
    base = max(RATE_FLOOR, min(RATE_CAP, r_port))
    cons = max(RATE_FLOOR, base - SCENARIO_SPREAD)
    opt = min(RATE_CAP, base + SCENARIO_SPREAD)
    return {
        "conservative_rate": cons,
        "base_rate": base,
        "optimistic_rate": opt,
        "conservative_fv": future_value(P, S, cons, n),
        "base_fv": future_value(P, S, base, n),
        "optimistic_fv": future_value(P, S, opt, n),
    }


# ============================================================
# Allocation engine
# ============================================================
def _band_for(horizon_months: int):
    for max_m, cap45, min12 in HORIZON_BANDS:
        if horizon_months <= max_m:
            return cap45, min12
    return HORIZON_BANDS[-1][1], HORIZON_BANDS[-1][2]


def _rt_cap_for_high_risk(rt_score: float) -> float:
    """Risk-tolerance-derived cap on risk-4/5 weight (stricter than horizon)."""
    if rt_score <= 1:
        return 0.0
    if rt_score <= 2:
        return 0.10
    if rt_score <= 3:
        return 0.25
    return 1.0


def _apply_preference(eligible, pref):
    if pref == "avoid_equity":
        filtered = [p for p in eligible if p["risk_score"] <= 2]
        return filtered or eligible
    if pref == "no_lock_in":
        filtered = [p for p in eligible if p["lock_in_months"] == 0]
        return filtered or eligible
    if pref == "capital_protection":
        filtered = [p for p in eligible if p["risk_score"] <= 2]
        return filtered or eligible
    return eligible


def build_allocation(profile: dict, products: list[dict]) -> Allocation:
    alloc = Allocation()
    by_id = {p["product_id"]: p for p in products}
    horizon = int(profile["horizon_months"])
    rt = float(profile["risk_tolerance_score"])
    cap45, min12 = _band_for(horizon)
    cap45 = min(cap45, _rt_cap_for_high_risk(rt))

    # --- Lock-in filter ---
    eligible = [p for p in products if p["lock_in_months"] <= horizon]
    if not eligible:
        alloc.exceptions.append(
            f"No product has a lock-in that fits the {horizon}-month horizon."
        )
        alloc.fallback_used = True
        cash = [p for p in products if p["risk_score"] == 1 and p["lock_in_months"] == 0]
        if cash:
            alloc.weights = {cash[0]["product_id"]: 1.0}
        return alloc

    eligible = _apply_preference(eligible, profile.get("preference", ""))

    # --- Reserve liquid buffer for emergency / liquidity need ---
    investable = profile["existing_investment_inr"]
    liquid_target = 0.0
    if investable > 0:
        if profile["liquidity_need_inr"] > 0:
            liquid_target = min(0.60, profile["liquidity_need_inr"] / investable)
        if profile["emergency_fund_months"] < 3:
            liquid_target = max(liquid_target, 0.25)

    liquid_candidates = sorted(
        [p for p in eligible if p["risk_score"] <= 2 and p["liquidity_days"] <= 5],
        key=lambda p: (p["risk_score"], p["annual_expense_ratio"]),
    )
    weights: dict[str, float] = {}
    if liquid_target > 0 and liquid_candidates:
        anchor = liquid_candidates[0]
        weights[anchor["product_id"]] = min(liquid_target, MAX_SINGLE_PRODUCT)

    # --- Fill remaining weight with best risk-compatible product ---
    remaining = 1.0 - sum(weights.values())

    pool = [p for p in eligible if p["product_id"] not in weights]
    pool.sort(key=lambda p: (p["risk_score"], p["annual_expense_ratio"],
                             -p["assumed_annual_return"]))

    risk45_used = sum(w for pid, w in weights.items() if by_id[pid]["risk_score"] >= 4)
    risk12_used = sum(w for pid, w in weights.items() if by_id[pid]["risk_score"] <= 2)

    # First pass: fill with risk<=3 products
    for p in [x for x in pool if x["risk_score"] <= 3]:
        if remaining <= 1e-9:
            break
        cap_here = min(MAX_SINGLE_PRODUCT, remaining)
        if p["risk_score"] >= 4:
            cap_here = min(cap_here, cap45 - risk45_used)
        if cap_here <= 1e-9:
            continue
        weights[p["product_id"]] = weights.get(p["product_id"], 0.0) + cap_here
        remaining -= cap_here
        if p["risk_score"] >= 4:
            risk45_used += cap_here
        if p["risk_score"] <= 2:
            risk12_used += cap_here

    # Second pass: allow risk-4/5 within cap if min-12 satisfied
    if remaining > 1e-9 and (risk12_used + 1e-9 >= min12 or horizon > 84):
        for p in [x for x in pool if x["risk_score"] >= 4]:
            if remaining <= 1e-9:
                break
            cap_here = min(MAX_SINGLE_PRODUCT, remaining, cap45 - risk45_used)
            if cap_here <= 1e-9:
                continue
            weights[p["product_id"]] = weights.get(p["product_id"], 0.0) + cap_here
            remaining -= cap_here
            risk45_used += cap_here

    # If remaining, push into risk<=2
    if remaining > 1e-9:
        for p in [x for x in eligible if x["risk_score"] <= 2]:
            if remaining <= 1e-9:
                break
            cap_here = min(MAX_SINGLE_PRODUCT - weights.get(p["product_id"], 0.0),
                           remaining)
            if cap_here <= 1e-9:
                continue
            weights[p["product_id"]] = weights.get(p["product_id"], 0.0) + cap_here
            remaining -= cap_here

    # Push any tiny residual into an existing product without breaking the 40% cap
    if remaining > 1e-9:
        for pid in sorted(weights, key=lambda k: weights[k]):
            room = MAX_SINGLE_PRODUCT - weights[pid]
            add = min(room, remaining)
            if add > 0:
                weights[pid] += add
                remaining -= add
            if remaining <= 1e-9:
                break

    # Absolute fallback if constraints are mathematically impossible
    if remaining > 1e-6 or not weights:
        alloc.warnings.append(
            "Constraints could not be satisfied with a fully diversified portfolio; "
            "using a conservative liquid-only fallback."
        )
        alloc.fallback_used = True
        cash = [p for p in products if p["risk_score"] == 1 and p["lock_in_months"] <= horizon]
        weights = {cash[0]["product_id"]: 1.0} if cash else {}

    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    alloc.weights = weights

    # Guardrail checks
    errs = validate_allocation(weights, [p["product_id"] for p in products])
    if errs:
        alloc.exceptions.extend(errs)

    wrisk = sum(w * by_id[pid]["risk_score"] for pid, w in weights.items())
    if wrisk > rt + 0.25 + 1e-6:
        alloc.warnings.append(
            f"Weighted risk {wrisk:.2f} exceeds tolerance {rt:.2f} + 0.25 buffer."
        )

    r45 = sum(w for pid, w in weights.items() if by_id[pid]["risk_score"] >= 4)
    r12 = sum(w for pid, w in weights.items() if by_id[pid]["risk_score"] <= 2)
    if r45 > cap45 + 1e-6:
        alloc.warnings.append(
            f"Risk-4/5 exposure {r45:.1%} exceeds horizon cap {cap45:.0%}."
        )
    if r12 + 1e-6 < min12:
        alloc.warnings.append(
            f"Risk-1/2 exposure {r12:.1%} below horizon minimum {min12:.0%}."
        )

    return alloc


# ============================================================
# Recommendation builder
# ============================================================
def recommend(profile: dict, products: list[dict]) -> Recommendation:
    by_id = {p["product_id"]: p for p in products}
    alloc = build_allocation(profile, products)
    investable = profile["existing_investment_inr"]

    allocations_out: dict[str, dict] = {}
    for pid, w in alloc.weights.items():
        p = by_id[pid]
        allocations_out[pid] = {
            "product_id": pid,
            "product_name": p["product_name"],
            "asset_class": p["asset_class"],
            "risk_score": p["risk_score"],
            "weight": round(w, 6),
            "amount_inr": round(w * investable, 2),
            "assumed_annual_return": p["assumed_annual_return"],
            "annual_expense_ratio": p["annual_expense_ratio"],
            "liquidity_days": p["liquidity_days"],
            "lock_in_months": p["lock_in_months"],
        }

    r_port = weighted_return(alloc.weights, by_id) if alloc.weights else 0.0
    scen = scenario_range(investable, profile["monthly_sip_inr"], r_port,
                          int(profile["horizon_months"]))
    target = profile["goal_amount_inr"]
    gap_base = scen["base_fv"] - target

    wrisk = sum(w * by_id[pid]["risk_score"] for pid, w in alloc.weights.items())
    wer = sum(w * by_id[pid]["annual_expense_ratio"] for pid, w in alloc.weights.items())
    annual_cost = wer * investable
    liquid_weight = sum(w for pid, w in alloc.weights.items()
                        if by_id[pid]["liquidity_days"] <= 5
                        and by_id[pid]["lock_in_months"] <= profile["horizon_months"])
    liquid_amt = liquid_weight * investable
    liquidity_ok = liquid_amt + 1e-6 >= profile["liquidity_need_inr"]

    warnings = list(alloc.warnings)
    if not liquidity_ok:
        warnings.append(
            f"Liquid allocation ₹{liquid_amt:,.0f} is below stated liquidity need "
            f"₹{profile['liquidity_need_inr']:,.0f}."
        )
    if gap_base < 0:
        warnings.append(
            f"Base-case shortfall ₹{-gap_base:,.0f} vs target ₹{target:,.0f}. "
            "Consider increasing SIP, extending horizon, or lowering target."
        )
    if scen["conservative_fv"] < target < scen["optimistic_fv"]:
        warnings.append(
            "Goal is feasible only in the optimistic scenario — treat as uncertain."
        )

    summary = {
        "investor_id": profile["investor_id"],
        "goal_label": profile["goal_label"],
        "target_inr": target,
        "horizon_months": int(profile["horizon_months"]),
        "existing_investment_inr": investable,
        "monthly_sip_inr": profile["monthly_sip_inr"],
        "weighted_return_pct": round(r_port * 100, 2),
        "weighted_risk_score": round(wrisk, 3),
        "weighted_expense_ratio_pct": round(wer * 100, 3),
        "estimated_annual_cost_inr": round(annual_cost, 2),
        "conservative_fv_inr": round(scen["conservative_fv"], 2),
        "base_fv_inr": round(scen["base_fv"], 2),
        "optimistic_fv_inr": round(scen["optimistic_fv"], 2),
        "gap_base_inr": round(gap_base, 2),
        "liquid_allocation_inr": round(liquid_amt, 2),
        "liquidity_need_inr": profile["liquidity_need_inr"],
        "liquidity_ok": liquidity_ok,
        "num_products": len(alloc.weights),
        "fallback_used": alloc.fallback_used,
        "emergency_fund_months": profile["emergency_fund_months"],
    }

    reasons = _build_reasons(profile, allocations_out, summary)
    return Recommendation(
        investor_id=profile["investor_id"],
        allocations=allocations_out,
        summary=summary,
        reasons=reasons,
        warnings=warnings,
        exceptions=list(alloc.exceptions),
    )


def _build_reasons(profile, allocations, summary) -> list[str]:
    reasons = []
    horizon = profile["horizon_months"]
    rt = profile["risk_tolerance_score"]
    pref = profile.get("preference", "")

    reasons.append(
        f"Horizon {horizon} months and risk tolerance {rt:.0f}/5 → "
        f"weighted risk kept at {summary['weighted_risk_score']:.2f}, "
        "respecting the horizon risk band and the 0.25 tolerance buffer."
    )
    if summary["liquid_allocation_inr"] > 0:
        reasons.append(
            f"₹{summary['liquid_allocation_inr']:,.0f} sits in liquid/short-settlement "
            f"products to cover the stated liquidity need of ₹{profile['liquidity_need_inr']:,.0f}."
        )
    if profile["emergency_fund_months"] < 3:
        reasons.append(
            "Emergency buffer < 3 months → liquid anchor prioritised before long-term allocation."
        )
    if pref:
        reasons.append(f"User preference '{pref}' applied as a filter on eligible products.")
    reasons.append(
        "Every product's lock-in ≤ goal horizon, and no single product exceeds 40% weight."
    )
    reasons.append(
        f"Blended expense ratio {summary['weighted_expense_ratio_pct']:.3f}% "
        f"(≈ ₹{summary['estimated_annual_cost_inr']:,.0f}/yr) — cost considered but "
        "not allowed to override suitability."
    )
    return reasons


# ============================================================
# What-if
# ============================================================
def whatif(profile: dict, products: list[dict], changes: dict) -> dict:
    """Apply named changes and recompute. Returns dict of before/after summaries."""
    base = recommend(profile, products)

    modified = dict(profile)
    for k, v in changes.items():
        if k == "market_shock_pct":
            pass # Handled below
        else:
            modified[k] = v

    aft = recommend(modified, products)

    shock = changes.get("market_shock_pct", 0)
    if shock:
        factor = 1 + shock / 100.0
        aft.summary["conservative_fv_inr"] *= factor
        aft.summary["base_fv_inr"] *= factor
        aft.summary["optimistic_fv_inr"] *= factor
        aft.summary["gap_base_inr"] = aft.summary["base_fv_inr"] - aft.summary["target_inr"]

    return {
        "before": base.summary,
        "after": aft.summary,
        "changes_applied": changes,
    }