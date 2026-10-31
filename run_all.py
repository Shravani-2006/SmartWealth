"""Batch runner: generate recommendation + summary CSVs for all personas."""
from __future__ import annotations
import os
import pandas as pd

from smartwealth import validate_profile, validate_products, recommend

os.makedirs("outputs", exist_ok=True)

profiles = pd.read_csv("data/investor_profiles.csv").to_dict("records")
products = pd.read_csv("data/investment_products.csv").to_dict("records")
for p in products:
    for f in ("risk_score", "assumed_annual_return", "annual_expense_ratio",
              "liquidity_days", "minimum_investment_inr", "lock_in_months"):
        p[f] = float(p[f])

errors = validate_products(products)
assert not errors, errors

alloc_rows, summ_rows = [], []
for raw in profiles:
    vr = validate_profile(raw)
    if not vr.ok:
        summ_rows.append({
            "investor_id": raw.get("investor_id"),
            "status": "INVALID",
            "errors": "; ".join(vr.errors),
        })
        continue
        
    rec = recommend(vr.profile, products)
    
    for pid, a in rec.allocations.items():
        alloc_rows.append({
            "investor_id": rec.investor_id,
            "product_id": pid,
            "product_name": a["product_name"],
            "asset_class": a["asset_class"],
            "risk_score": a["risk_score"],
            "weight": a["weight"],
            "amount_inr": a["amount_inr"],
            "annual_expense_ratio": a["annual_expense_ratio"],
            "liquidity_days": a["liquidity_days"],
            "lock_in_months": a["lock_in_months"],
        })
        
    # Combine base summary with warning strings for CSV readability
    summary_data = dict(rec.summary)
    warnings_list = summary_data.pop("warnings", [])
    if warnings_list:
        summary_data["warnings"] = " | ".join(warnings_list)
    else:
        summary_data["warnings"] = "None"

    summ_rows.append({
        "investor_id": rec.investor_id,
        "status": "OK",
        **summary_data
    })

# Save outputs
pd.DataFrame(alloc_rows).to_csv("outputs/recommendations_allocations.csv", index=False)
pd.DataFrame(summ_rows).to_csv("outputs/recommendations_summary.csv", index=False)

print(f"Generated {len(alloc_rows)} allocation rows and {len(summ_rows)} summary rows in the outputs/ directory.")