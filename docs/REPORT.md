# SmartWealth 5-Minute Demo Script

**Setup:** Run `streamlit run app.py` or use the CLI.

### 1. Conservative Short-Horizon Investor (2 mins)
- **Select Persona**: `INV03` (Home renovation, 15 months, Risk 1, Beginner).
- **Show**: The app correctly identifies the short horizon. It allocates heavily to PROD01 (Cash) and PROD03 (Short Debt). 
- **Point out**: No equity (Risk 4-5) is allocated due to the <36-month guardrail (10% max). The weighted risk is well under the limit.
- **Warning**: Notice the emergency fund warning (4 months is okay, but liquidity need of 50k is met by cash).

### 2. Long-Horizon Investor (1.5 mins)
- **Select Persona**: `INV06` (Retirement corpus, 240 months, 1.5 Cr goal, Risk 2, Beginner, Preference: avoid_equity).
- **Show**: Because of the `avoid_equity` preference, PROD06 and PROD08 are excluded.
- **Point out**: The system allocates to Debt and Hybrid (PROD05), balancing the long horizon with the strict risk cap. 
- **Explain**: The projection shows a base case, but warns of a shortfall. It suggests increasing SIP to meet the 1.5 Cr target.

### 3. Edge Case / Infeasible Goal (1.5 mins)
- **Select Persona**: `INV11` (Higher studies, 84 months, 4 Lakh goal, 0 existing, 3k SIP).
- **Show**: The goal is feasible, but look at `INV08` (Start a business, 36 months, 50 Lakh goal, 20k SIP). The projection shows a massive shortfall.
- **Action**: Go to the "What-If" sidebar and change `INV08`'s Risk Tolerance from 3 to 1.
- **Result**: The engine immediately drops the high-growth assets, shifts to debt, and the shortfall widens. The warning updates to show the exact SIP required to meet the goal if the user insists on Risk 1.
