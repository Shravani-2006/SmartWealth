"""SmartWealth Streamlit UI — Polished, Theme-Aware FinTech Dashboard."""
from __future__ import annotations
import pandas as pd
import streamlit as st
import plotly.express as px

from smartwealth import (
    validate_profile, validate_products, recommend, whatif,
)

# ============================================================
# Page Config & Custom CSS
# ============================================================
st.set_page_config(page_title="SmartWealth | Goal Planner", page_icon="💡", layout="wide")

# This CSS is designed to work in BOTH Light and Dark modes
st.markdown("""
<style>
    /* Improve spacing and typography */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Make metric cards look modern using native theme colors */
    div[data-testid="stMetric"] {
        background-color: rgba(128, 128, 128, 0.1);
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 1rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    div[data-testid="stMetricValue"] {
        font-size: 2rem !important;
    }
    
    /* Modernize the sidebar inputs */
    section[data-testid="stSidebar"] {
        padding-top: 1rem;
    }
    
    /* Style the primary button */
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Data Loading
# ============================================================
@st.cache_data
def load_data():
    profiles = pd.read_csv("data/investor_profiles.csv")
    products = pd.read_csv("data/investment_products.csv")
    products_list = products.to_dict("records")
    for p in products_list:
        for f in ("risk_score", "assumed_annual_return", "annual_expense_ratio",
                  "liquidity_days", "minimum_investment_inr", "lock_in_months"):
            p[f] = float(p[f])
    return profiles, products_list

profiles_df, products_list = load_data()
prod_errors = validate_products(products_list)
if prod_errors:
    st.error("Product catalogue errors: " + "; ".join(prod_errors))
    st.stop()

# ============================================================
# Sidebar
# ============================================================
st.sidebar.title("⚙️ Profile Setup")
mode = st.sidebar.radio("Mode", ["Select persona", "Custom profile"], horizontal=True)

if mode == "Select persona":
    pid = st.sidebar.selectbox("Persona", profiles_df["investor_id"].tolist())
    raw = profiles_df[profiles_df["investor_id"] == pid].iloc[0].to_dict()
else:
    raw = {
        "investor_id": "CUSTOM", "goal_label": "Custom goal",
        "goal_amount_inr": 1000000.0, "horizon_months": 60.0,
        "existing_investment_inr": 200000.0, "monthly_sip_inr": 10000.0,
        "risk_tolerance_score": 3.0, "emergency_fund_months": 6.0,
        "liquidity_need_inr": 0.0, "experience": "intermediate", "preference": "",
    }

with st.sidebar.form("edit_profile"):
    st.markdown("### Editable Inputs")
    goal = st.number_input("Goal Amount (₹)", value=float(raw["goal_amount_inr"]), step=50000.0)
    horizon = st.number_input("Horizon (months)", value=int(raw["horizon_months"]), step=6)
    
    existing = st.number_input("Existing Investment (₹)", value=float(raw["existing_investment_inr"]), step=10000.0)
    sip = st.number_input("Monthly SIP (₹)", value=float(raw["monthly_sip_inr"]), step=1000.0)
    
    rt = st.slider("Risk Tolerance (1-5)", 1, 5, int(raw["risk_tolerance_score"]))
    
    em = st.number_input("Emergency Fund (months)", value=float(raw["emergency_fund_months"]), step=1.0)
    liq = st.number_input("Liquidity Need (₹)", value=float(raw["liquidity_need_inr"]), step=10000.0)
    
    pref_options = ["", "avoid_equity", "capital_protection", "no_lock_in", 
                    "low_cost", "high_growth", "tax_saving"]
    raw_pref = raw.get("preference")
    pref_str = str(raw_pref).strip() if pd.notna(raw_pref) else ""
    if pref_str not in pref_options:
        pref_str = ""
        
    pref = st.selectbox("Preference Filter", pref_options, index=pref_options.index(pref_str))
    
    submitted = st.form_submit_button("🚀 Generate Plan", use_container_width=True)

edited = dict(raw)
edited.update({
    "goal_amount_inr": goal, "horizon_months": horizon,
    "existing_investment_inr": existing, "monthly_sip_inr": sip,
    "risk_tolerance_score": rt, "emergency_fund_months": em,
    "liquidity_need_inr": liq, "preference": pref,
})

# ============================================================
# Validation & Recommendation
# ============================================================
vr = validate_profile(edited)
if not vr.ok:
    st.error("### Invalid Profile Inputs")
    for e in vr.errors:
        st.write("❌ " + e)
    st.stop()

profile = vr.profile
rec = recommend(profile, products_list)

# ============================================================
# Main Dashboard
# ============================================================
st.title("💡 SmartWealth Recommendation")
st.markdown(f"**Goal:** {profile['goal_label']} (Target: ₹{profile['goal_amount_inr']:,.0f})")
st.caption("Educational simulation only. Not personal financial advice. Returns are synthetic estimates.")

# --- Warnings & Feasibility ---
gap = rec.summary["gap_base_inr"]
if gap >= 0:
    st.success(f"✅ **Goal is likely feasible.** The base-case projection shows a surplus of **₹{gap:,.0f}**.")
else:
    st.error(f"⚠️ **Goal infeasibility warning.** The base-case projection shows a shortfall of **₹{-gap:,.0f}**. Consider increasing SIP or extending horizon.")

for w in vr.warnings + rec.warnings:
    st.warning(w)
for e in rec.exceptions:
    st.error(f"**Guardrail Exception:** {e}")

st.divider()

# --- Top Level Metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Portfolio Risk Score", f"{rec.summary['weighted_risk_score']:.2f} / 5.00")
col2.metric("Base Case Future Value", f"₹{rec.summary['base_fv_inr']:,.0f}")
col3.metric("Blended Expense Ratio", f"{rec.summary['weighted_expense_ratio_pct']:.3f}%")
col4.metric("Annual Product Cost", f"₹{rec.summary['estimated_annual_cost_inr']:,.0f}")

st.write("") # Spacer

# --- Allocation & Chart Section ---
st.subheader("Recommended Allocation")
alloc_df = pd.DataFrame(list(rec.allocations.values()))

if not alloc_df.empty:
    alloc_df["weight_pct"] = (alloc_df["weight"] * 100).round(2)
    
    c_table, c_chart = st.columns([3, 2])
    
    with c_table:
        st.dataframe(
            alloc_df[["product_name", "asset_class", "risk_score", "weight_pct", "amount_inr"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "product_name": "Product",
                "asset_class": "Asset Class",
                "risk_score": "Risk",
                "weight_pct": st.column_config.NumberColumn("Weight %", format="%.2f%%"),
                "amount_inr": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
            }
        )
    with c_chart:
        # A beautiful donut chart that respects dark mode
        fig = px.pie(
            alloc_df, 
            values="weight", 
            names="asset_class", 
            hole=0.5,
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.update_layout(
            margin=dict(t=10, b=10, l=10, r=10), 
            showlegend=True,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888")
        )
        st.plotly_chart(fig, use_container_width=True)

# --- Projection Chart ---
st.subheader("Goal Projection Range")
proj_df = pd.DataFrame({
    "Scenario": ["Conservative", "Base Case", "Optimistic"],
    "Future Value (₹)": [
        rec.summary['conservative_fv_inr'], 
        rec.summary['base_fv_inr'], 
        rec.summary['optimistic_fv_inr']
    ]
})

fig_proj = px.bar(
    proj_df, 
    x="Scenario", 
    y="Future Value (₹)", 
    color="Scenario",
    color_discrete_map={"Conservative": "#F87171", "Base Case": "#60A5FA", "Optimistic": "#34D399"},
    text="Future Value (₹)"
)
fig_proj.update_traces(texttemplate='₹%{text:,.0f}', textposition='outside')
fig_proj.update_layout(
    showlegend=False, 
    yaxis_title="Future Value (₹)", 
    margin=dict(t=40, b=10, l=10, r=10),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#888888")
)
fig_proj.add_hline(y=profile['goal_amount_inr'], line_dash="dash", line_color="#FBBF24", annotation_text="Target Goal")
st.plotly_chart(fig_proj, use_container_width=True)

# --- Explainability Section ---
st.subheader("Why these products?")
for r in rec.reasons:
    st.markdown(f"- {r}")

st.divider()

# ============================================================
# What-If Simulator
# ============================================================
st.subheader("⚡ What-If Simulator")
st.markdown("Adjust the parameters below to see how the plan changes.")

with st.container():
    with st.form("whatif_sim"):
        c1, c2, c3, c4 = st.columns(4)
        shock = c1.number_input("Market Shock (%)", value=-15.0, step=1.0)
        sip_factor = c2.slider("SIP Change (%)", -50, 50, -20)
        new_horizon = c3.number_input("New Horizon (months)", value=int(profile["horizon_months"]), step=6)
        new_rt = c4.slider("New Risk Tolerance", 1, 5, int(profile["risk_tolerance_score"]))
        run = st.form_submit_button("Run Simulation", use_container_width=True)

if run:
    changes = {
        "market_shock_pct": shock,
        "monthly_sip_inr": max(0.0, profile["monthly_sip_inr"] * (1 + sip_factor / 100.0)),
        "horizon_months": new_horizon,
        "risk_tolerance_score": new_rt,
    }
    res = whatif(profile, products_list, changes)
    
    st.markdown("### Simulation Results")
    r1, r2, r3 = st.columns(3)
    r1.metric("Original Base FV", f"₹{res['before']['base_fv_inr']:,.0f}")
    r2.metric("Simulated Base FV", f"₹{res['after']['base_fv_inr']:,.0f}", 
              delta=f"₹{res['after']['base_fv_inr'] - res['before']['base_fv_inr']:,.0f}")
    
    new_gap = res['after']['gap_base_inr']
    if new_gap >= 0:
        r3.metric("Simulated Gap", f"₹{new_gap:,.0f} Surplus")
    else:
        r3.metric("Simulated Gap", f"₹{-new_gap:,.0f} Shortfall", delta_color="inverse")
        
    diff = pd.DataFrame([res["before"], res["after"]], index=["Original", "Simulated"]).T
    st.dataframe(diff, use_container_width=True)

# ============================================================
# Downloads
# ============================================================
st.divider()
c_dl1, c_dl2 = st.columns(2)
if not alloc_df.empty:
    csv1 = alloc_df.drop(columns=["weight_pct"], errors="ignore").to_csv(index=False)
    c_dl1.download_button("📥 Download Allocation CSV", csv1, "allocation.csv", "text/csv", use_container_width=True)

summ_df = pd.DataFrame([rec.summary])
csv2 = summ_df.to_csv(index=False)
c_dl2.download_button("📥 Download Summary CSV", csv2, "summary.csv", "text/csv", use_container_width=True)