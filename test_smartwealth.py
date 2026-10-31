"""Automated tests for the SmartWealth recommendation engine."""
import pytest
import math
import pandas as pd
from smartwealth import validate_profile, validate_products, recommend

# --- Fixtures ---

@pytest.fixture
def sample_products():
    """Loads and parses the product catalogue for testing."""
    products = pd.read_csv("data/investment_products.csv").to_dict("records")
    for p in products:
        for f in ("risk_score", "assumed_annual_return", "annual_expense_ratio",
                  "liquidity_days", "minimum_investment_inr", "lock_in_months"):
            p[f] = float(p[f])
    return products

@pytest.fixture
def base_profile():
    """A standard, valid profile to be modified by specific tests."""
    return {
        "investor_id": "TEST01",
        "goal_label": "Test Goal",
        "goal_amount_inr": 1000000.0,
        "horizon_months": 24.0,
        "existing_investment_inr": 100000.0,
        "monthly_sip_inr": 10000.0,
        "risk_tolerance_score": 3.0,
        "emergency_fund_months": 6.0,
        "liquidity_need_inr": 0.0,
        "experience": "intermediate",
        "preference": ""
    }

# --- Tests ---

def test_allocation_sums_to_100_percent(sample_products, base_profile):
    """1. Verify weights are non-negative and sum to 100% within 0.1% tolerance."""
    vr = validate_profile(base_profile)
    assert vr.ok
    rec = recommend(vr.profile, sample_products)
    
    total_weight = sum(a["weight"] for a in rec.allocations.values())
    
    # Check sum
    assert math.isclose(total_weight, 1.0, abs_tol=0.001), f"Weights sum to {total_weight}, not 1.0"
    
    # Check non-negative
    for pid, a in rec.allocations.items():
        assert a["weight"] >= 0, f"Negative weight found for {pid}"

def test_lock_in_horizon_rule(sample_products, base_profile):
    """2. Verify no product with a lock-in longer than the horizon is allocated."""
    # Set horizon to 12 months (less than PROD02's 24mo and PROD07's 36mo)
    base_profile["horizon_months"] = 12.0
    vr = validate_profile(base_profile)
    rec = recommend(vr.profile, sample_products)
    
    for pid, a in rec.allocations.items():
        assert a["lock_in_months"] <= base_profile["horizon_months"], \
            f"Allocated {pid} with lock-in {a['lock_in_months']} > horizon {base_profile['horizon_months']}"

def test_risk_tolerance_cap(sample_products, base_profile):
    """3. Verify the weighted portfolio risk does not exceed tolerance by >0.25."""
    # Force strict risk limit
    base_profile["risk_tolerance_score"] = 2.0
    vr = validate_profile(base_profile)
    rec = recommend(vr.profile, sample_products)
    
    weighted_risk = rec.summary["weighted_risk_score"]
    max_allowed = base_profile["risk_tolerance_score"] + 0.25
    
    assert weighted_risk <= max_allowed, \
        f"Portfolio risk {weighted_risk} exceeds cap {max_allowed}"

def test_diversification_cap(sample_products, base_profile):
    """4. Verify no single product exceeds the 40% diversification limit."""
    vr = validate_profile(base_profile)
    rec = recommend(vr.profile, sample_products)
    
    for pid, a in rec.allocations.items():
        assert a["weight"] <= 0.40 + 0.0001, f"{pid} exceeds 40% weight limit (got {a['weight']})"

def test_malformed_profile_handling():
    """5. Verify that invalid data is caught explicitly and does not crash."""
    bad_profile = {
        "investor_id": "BAD01",
        "goal_amount_inr": -5000,       # Invalid: negative goal
        "horizon_months": "abc",        # Invalid: non-numeric
        "risk_tolerance_score": 10,     # Invalid: out of bounds (1-5)
        "existing_investment_inr": 0,
        "monthly_sip_inr": 0,
        "emergency_fund_months": 0,
        "liquidity_need_inr": 0,
        "experience": "beginner",
        "goal_label": "Fail Goal",
        "preference": ""
    }
    
    vr = validate_profile(bad_profile)
    assert not vr.ok, "Profile should have been marked invalid"
    assert len(vr.errors) >= 3, "Expected multiple validation errors"

def test_short_horizon_conservative_allocation(sample_products, base_profile):
    """6. Verify short horizons (<36mo) allocate at least 70% to low-risk (1-2) products."""
    base_profile["horizon_months"] = 24.0
    vr = validate_profile(base_profile)
    rec = recommend(vr.profile, sample_products)
    
    low_risk_weight = sum(
        a["weight"] for a in rec.allocations.values() 
        if a["risk_score"] <= 2.0
    )
    
    assert low_risk_weight >= 0.70 - 0.001, f"Low-risk allocation {low_risk_weight} below 70% for short horizon"