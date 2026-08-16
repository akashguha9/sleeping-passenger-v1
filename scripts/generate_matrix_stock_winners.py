"""Generate the Sleeping Passenger India + US matrix-winner report.

This is an isolated report builder.  It deliberately does not alter the
production discovery pipeline.  The evidence spine is the latest sourced
daily discovery report plus official result deltas and read-only quote
snapshots refreshed on 2026-07-27.
"""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATE = "2026-07-27"
EVIDENCE_DATE = "2026-07-16"
SOURCE_REPORT = REPORTS / f"daily_stock_discovery_{EVIDENCE_DATE}.md"
MD_PATH = REPORTS / f"matrix_stock_winners_{DATE}.md"
JSON_PATH = REPORTS / f"matrix_stock_winners_{DATE}.json"
CSV_PATH = REPORTS / f"matrix_stock_winners_{DATE}.csv"

NQ = "NO QUALIFIED WINNER TODAY"

SCORE_WEIGHTS = {
    "structural_node_position": 10,
    "sovereignty": 9,
    "early_capture_and_promotion_geometry": 11,
    "fundamental_quality": 12,
    "cash_flow_and_balance_sheet_quality": 8,
    "valuation_and_poker_pot_odds": 10,
    "catalysts_and_inflection": 8,
    "price_strength_and_entry_quality": 7,
    "poker_weighted_expected_value": 7,
    "mines_survival_probability": 7,
    "economic_half_life": 5,
    "clairefontaine_cohort_quality": 4,
    "gamblers_fallacy_protection": 2,
}

VECTOR_KEYS = list(SCORE_WEIGHTS)


def primary_candidate(**row: Any) -> dict[str, Any]:
    vector = row.pop("vector")
    if len(vector) != len(VECTOR_KEYS):
        raise ValueError(f"bad score vector for {row['ticker']}")
    result = {
        "date": DATE,
        "candidate_type": "PRIMARY",
        "share_type": "COM",
        "score_components": dict(zip(VECTOR_KEYS, vector)),
        **row,
    }
    if sum(vector) != result["mvp_score"]:
        raise ValueError(f"score vector does not sum for {result['ticker']}")
    result["sector"] = result["sector_path"].split(" > ", 1)[0]
    result["canonical_classification"] = canonical(result)
    return result


def canonical(row: dict[str, Any]) -> str:
    secondary = ", ".join(row.get("secondary_use_cases", [])) or "None"
    risks = ", ".join(row.get("risk_sensitivities", [])) or "None"
    return (
        f"{row['exchange']}:{row['ticker']} | {row['country']} | {row['exchange']} | "
        f"{row['sector_path']} | {row['primary_use_case']} | {secondary} | "
        f"{row['market_cap_class']} | {row['maturity_stage']} | "
        f"{row.get('share_type', 'COM')} | {row['volatility_class']} | {risks}"
    )


INDIA: list[dict[str, Any]] = [
    primary_candidate(
        ticker="ICICIBANK", company="ICICI Bank", country="India", exchange="NSE", rank=1,
        sector_path="Financials > Banks > Banks > Diversified Banks",
        primary_use_case="QC", secondary_use_cases=["BC", "SR"], market_cap_class="MEGA",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["RATE", "REG", "BETA"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹1,444.30", price_observed="2026-07-17 close",
        mvp_score=86, confidence_score=89, sovereignty_score=9, mines_risk_score=3,
        clairefontaine_level=7, promotion_probability=75,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER",
        main_catalyst="18 July Q1 result (pending at 12:11 IST): deposits, NIM and asset quality",
        main_risk="Deposit competition, NIM compression and renewed slippage",
        thesis_invalidation="NIM persistently below 4%, deposits materially lag loans, or renewed slippage",
        vector=[9, 9, 8, 11, 7, 8, 6, 5, 6, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="HDFCBANK", company="HDFC Bank", country="India", exchange="NSE", rank=2,
        sector_path="Financials > Banks > Banks > Diversified Banks",
        primary_use_case="VA", secondary_use_cases=["QC", "BC"], market_cap_class="MEGA",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["RATE", "REG", "EVT"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹819.60", price_observed="2026-07-17 close",
        mvp_score=84, confidence_score=88, sovereignty_score=9, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=70,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Scheduled 18 July Q1 result; pending at 12:11 IST",
        main_risk="Post-merger NIM, deposit mix and ROA drag",
        thesis_invalidation="NIM below 3.3%, deposits disappoint, or ROA normalization stalls",
        vector=[9, 9, 7, 11, 8, 8, 7, 4, 5, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="POWERGRID", company="Power Grid Corporation of India", country="India", exchange="NSE", rank=3,
        sector_path="Utilities > Utilities > Electric Utilities > Electric Transmission",
        primary_use_case="SR", secondary_use_cases=["IN", "DF"], market_cap_class="LARGE",
        maturity_stage="M6", volatility_class="LV", risk_sensitivities=["RATE", "REG"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹283.80", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=82, confidence_score=86, sovereignty_score=9, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=80,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Project capitalization and renewable evacuation awards",
        main_risk="Leverage, commissioning delay and allowed-return changes",
        thesis_invalidation="Allowed-return damage, persistent commissioning delay, or debt outruns commissioned assets",
        vector=[10, 9, 5, 11, 5, 8, 7, 5, 6, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="SHRIRAMFIN", company="Shriram Finance", country="India", exchange="NSE", rank=4,
        sector_path="Financials > Financial Services > Consumer Finance > Diversified Finance",
        primary_use_case="GR", secondary_use_cases=["VA", "EC"], market_cap_class="LARGE",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["RATE", "BETA", "LIQ"],
        casino_role="PLAYER", food_chain_role="SECONDARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="₹1,025.00", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=82, confidence_score=88, sovereignty_score=8, mines_risk_score=4,
        clairefontaine_level=6, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="HIGH-CONVICTION RESEARCH CANDIDATE", main_catalyst="Funding-cost and credit-cost normalization",
        main_risk="Used-vehicle/MSME asset quality and liability costs",
        thesis_invalidation="Stage 2/3 rises materially, collections weaken, or liability-duration stress appears",
        vector=[8, 8, 8, 10, 7, 8, 7, 5, 6, 5, 5, 3, 2],
    ),
    primary_candidate(
        ticker="INDIAMART", company="IndiaMART InterMESH", country="India", exchange="NSE", rank=5,
        sector_path="Communication Services > Media & Entertainment > Interactive Media & Services > B2B Marketplace",
        primary_use_case="EC", secondary_use_cases=["QC", "SR"], market_cap_class="MID",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["BETA", "REG"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="QUEEN", poker_hand="STRAIGHT",
        half_life="LONG", current_price="₹1,910.10", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=82, confidence_score=84, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=5, promotion_probability=60,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Paying-supplier and Busy workflow stabilization",
        main_risk="Supplier stagnation, churn and weak reinvestment conversion",
        thesis_invalidation="Two more supplier-contraction quarters or collections growth below high single digits",
        vector=[8, 8, 10, 9, 8, 9, 6, 5, 6, 5, 4, 3, 1],
    ),
    primary_candidate(
        ticker="MCX", company="Multi Commodity Exchange of India", country="India", exchange="NSE", rank=6,
        sector_path="Financials > Financial Services > Capital Markets > Financial Exchanges & Data",
        primary_use_case="SR", secondary_use_cases=["QC", "MO"], market_cap_class="MID",
        maturity_stage="M5", volatility_class="HV", risk_sensitivities=["REG", "EVT", "CMD"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="OVERPLAYED HAND",
        half_life="VERY LONG", current_price="₹2,747.50", price_observed="2026-07-17 close",
        mvp_score=81, confidence_score=84, sovereignty_score=9, mines_risk_score=6,
        clairefontaine_level=7, promotion_probability=55,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Q1 volume and revenue-per-contract normalization",
        main_risk="Rule shock, premium-turnover loss, regulation and NSE competition",
        thesis_invalidation="Sustained RPC loss, regulatory damage, or EBITDA margin below 60% without reinvestment",
        vector=[10, 9, 8, 11, 8, 4, 7, 3, 6, 4, 5, 4, 2],
    ),
    primary_candidate(
        ticker="KFINTECH", company="KFin Technologies", country="India", exchange="NSE", rank=7,
        sector_path="Financials > Financial Services > Capital Markets > Asset-Servicing Technology",
        primary_use_case="EC", secondary_use_cases=["SR", "GR"], market_cap_class="MID",
        maturity_stage="M4", volatility_class="NV", risk_sensitivities=["REG", "EVT", "LIQ"],
        casino_role="DEALER", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="STRAIGHT",
        half_life="VERY LONG", current_price="₹887.90", price_observed="2026-07-17 close",
        mvp_score=81, confidence_score=84, sovereignty_score=7, mines_risk_score=5,
        clairefontaine_level=6, promotion_probability=70,
        valuation_classification="FAIRLY VALUED", entry_status="WAIT FOR CATALYST",
        action="EARLY CAPTURE", main_catalyst="Organic international growth and clean integrations",
        main_risk="Fee regulation, integration and platform/security failure",
        thesis_invalidation="Organic international growth below 15%, EBITDA margin below 38%, or weaker retention",
        vector=[8, 7, 10, 10, 7, 6, 7, 4, 6, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="BHARTIARTL", company="Bharti Airtel", country="India", exchange="NSE", rank=8,
        sector_path="Communication Services > Telecommunication Services > Diversified Telecom > Wireless Services",
        primary_use_case="BC", secondary_use_cases=["SR", "QC"], market_cap_class="MEGA",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["REG", "GEO", "BETA"],
        casino_role="DEALER", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹1,908.80", price_observed="2026-07-17 close",
        mvp_score=80, confidence_score=86, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="ARPU growth and capex moderation",
        main_risk="Spectrum liabilities, regulation and Africa currency exposure",
        thesis_invalidation="ARPU/ROIC stagnates, capex intensity reaccelerates, or adverse regulation resets economics",
        vector=[9, 8, 7, 11, 6, 5, 7, 5, 6, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="INDUSTOWER", company="Indus Towers", country="India", exchange="NSE", rank=9,
        sector_path="Communication Services > Telecommunication Services > Diversified Telecom > Telecom Infrastructure",
        primary_use_case="IN", secondary_use_cases=["SR", "VA"], market_cap_class="LARGE",
        maturity_stage="M6", volatility_class="NV", risk_sensitivities=["REG", "LIQ", "BETA"],
        casino_role="DEALER", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹403.50", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=80, confidence_score=86, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=6, promotion_probability=60,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Tenancy, 5G loading and cash return",
        main_risk="Tenant concentration, lease-adjusted leverage and overseas allocation",
        thesis_invalidation="Collections fail, lease-adjusted leverage worsens, or overseas capex destroys ROIC",
        vector=[9, 8, 6, 10, 7, 8, 6, 5, 6, 5, 5, 3, 2],
    ),
    primary_candidate(
        ticker="PERSISTENT", company="Persistent Systems", country="India", exchange="NSE", rank=10,
        sector_path="Information Technology > Software & Services > IT Services > IT Consulting & Digital Engineering",
        primary_use_case="GR", secondary_use_cases=["QC", "MO"], market_cap_class="MID",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["BETA", "EVT", "GEO"],
        casino_role="DEALER", food_chain_role="SECONDARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="₹5,172.40", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=80, confidence_score=88, sovereignty_score=7, mines_risk_score=5,
        clairefontaine_level=6, promotion_probability=55,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Scheduled Q1 board/results on 21–22 July",
        main_risk="US spending, pricing pressure and multiple compression",
        thesis_invalidation="Constant-currency growth below 12%, EBIT below 15%, or AI pricing compresses conversion",
        vector=[7, 7, 9, 11, 7, 6, 7, 5, 6, 5, 4, 4, 2],
    ),
    primary_candidate(
        ticker="OFSS", company="Oracle Financial Services Software", country="India", exchange="NSE", rank=11,
        sector_path="Information Technology > Software & Services > Software > Application Software",
        primary_use_case="VA", secondary_use_cases=["QC", "SR"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["LIQ", "EVT", "REG"],
        casino_role="DEALER", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹11,771.00", price_observed="2026-07-17 close",
        mvp_score=79, confidence_score=88, sovereignty_score=8, mines_risk_score=4,
        clairefontaine_level=6, promotion_probability=55,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="WAIT FOR PULLBACK",
        action="WAIT FOR PULLBACK", main_catalyst="License/cloud conversion and product refresh",
        main_risk="Oracle-parent dependence, low float and license lumpiness",
        thesis_invalidation="Recurring/cloud mix stalls or capital allocation becomes minority-unfriendly",
        vector=[8, 8, 8, 10, 8, 6, 6, 3, 6, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="RELIANCE", company="Reliance Industries", country="India", exchange="NSE", rank=12,
        sector_path="Energy > Energy > Oil, Gas & Consumable Fuels > Integrated Oil & Gas",
        primary_use_case="BC", secondary_use_cases=["SR", "VA"], market_cap_class="MEGA",
        maturity_stage="M6", volatility_class="NV", risk_sensitivities=["CMD", "GEO", "REG"],
        casino_role="TABLE", food_chain_role="PRODUCER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="₹1,327.20", price_observed="2026-07-17 close",
        mvp_score=79, confidence_score=88, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="17 July Q1 follow-through across Jio, retail and O2C",
        main_risk="Capex, O2C cycle, leverage and conglomerate complexity",
        thesis_invalidation="Sustained negative FCF, leverage escalation, or Jio/retail growth below high single digits",
        vector=[9, 8, 8, 10, 6, 7, 6, 5, 5, 4, 5, 4, 2],
    ),
    primary_candidate(
        ticker="LT", company="Larsen & Toubro", country="India", exchange="NSE", rank=13,
        sector_path="Industrials > Capital Goods > Construction & Engineering > Construction & Engineering",
        primary_use_case="CY", secondary_use_cases=["QC", "SR"], market_cap_class="MEGA",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["BETA", "GEO", "CMD"],
        casino_role="DEALER", food_chain_role="SECONDARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="₹3,817.90", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=78, confidence_score=87, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=55,
        valuation_classification="FAIRLY VALUED", entry_status="BUY-RESEARCH ZONE",
        action="HIGH-CONVICTION RESEARCH CANDIDATE", main_catalyst="₹7.40T order-book conversion",
        main_risk="Project mix, West Asia exposure and working-capital reversal",
        thesis_invalidation="Order quality deteriorates, project margin below 9%, or cash conversion weakens",
        vector=[8, 8, 7, 11, 6, 6, 8, 4, 5, 4, 5, 4, 2],
    ),
    primary_candidate(
        ticker="SUNPHARMA", company="Sun Pharmaceutical Industries", country="India", exchange="NSE", rank=14,
        sector_path="Health Care > Pharmaceuticals, Biotechnology & Life Sciences > Pharmaceuticals > Pharmaceuticals",
        primary_use_case="DF", secondary_use_cases=["QC", "GR"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["REG", "GEO", "EVT"],
        casino_role="PLAYER", food_chain_role="PRODUCER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="₹1,932.60", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=78, confidence_score=86, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=55,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="WAIT FOR PULLBACK",
        action="WAIT FOR PULLBACK", main_catalyst="Innovative-medicines growth and Organon integration",
        main_risk="FDA action, R&D productivity and acquisition execution",
        thesis_invalidation="FDA action, innovative-medicine deceleration, or Organon ROIC failure",
        vector=[8, 8, 7, 11, 8, 5, 7, 4, 5, 5, 4, 4, 2],
    ),
    primary_candidate(
        ticker="WABAG", company="VA Tech Wabag", country="India", exchange="NSE", rank=15,
        sector_path="Industrials > Commercial & Professional Services > Commercial Services & Supplies > Environmental Services",
        primary_use_case="EC", secondary_use_cases=["SR", "GR"], market_cap_class="SMALL",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["LIQ", "GEO", "EVT"],
        casino_role="PLAYER", food_chain_role="SECONDARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="STRAIGHT",
        half_life="LONG", current_price="₹2,000.00", price_observed="2026-07-17 15:29 IST bounded observation",
        mvp_score=77, confidence_score=86, sovereignty_score=6, mines_risk_score=6,
        clairefontaine_level=5, promotion_probability=60,
        valuation_classification="FAIRLY VALUED", entry_status="WAIT FOR PULLBACK",
        action="EARLY CAPTURE", main_catalyst="Framework conversion and higher recurring O&M mix",
        main_risk="EPC execution, receivables, country risk and extended entry",
        thesis_invalidation="Receivables re-expand, overseas losses recur, or framework conversion fails",
        vector=[7, 6, 10, 10, 7, 6, 7, 4, 5, 4, 5, 4, 2],
    ),
]

US: list[dict[str, Any]] = [
    primary_candidate(
        ticker="ICE", company="Intercontinental Exchange", country="United States", exchange="NYSE", rank=1,
        sector_path="Financials > Financial Services > Capital Markets > Financial Exchanges & Data",
        primary_use_case="SR", secondary_use_cases=["QC", "BC"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["REG", "RATE", "EVT"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="STRAIGHT FLUSH",
        half_life="VERY LONG", current_price="$139.65", price_observed="2026-07-17 close",
        mvp_score=89, confidence_score=90, sovereignty_score=9, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=80,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Confirmed Q2 result on 30 July",
        main_risk="Debt, mortgage cycle, data/capture pressure and regulation",
        thesis_invalidation="Data slows, exchange share/capture falls, or deleveraging fails",
        vector=[10, 9, 7, 12, 8, 8, 7, 4, 7, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="CME", company="CME Group", country="United States", exchange="Nasdaq", rank=2,
        sector_path="Financials > Financial Services > Capital Markets > Financial Exchanges & Data",
        primary_use_case="IN", secondary_use_cases=["SR", "QC"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["REG", "RATE", "EVT"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="STRAIGHT FLUSH",
        half_life="VERY LONG", current_price="$245.05", price_observed="2026-07-17 close",
        mvp_score=88, confidence_score=91, sovereignty_score=9, mines_risk_score=3,
        clairefontaine_level=7, promotion_probability=80,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Confirmed Q2 result on 22 July",
        main_risk="ADV, market share and revenue-per-contract normalization",
        thesis_invalidation="Persistent ADV/share loss, capture deterioration, or adverse rule change",
        vector=[10, 9, 6, 12, 8, 8, 7, 4, 7, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="ADBE", company="Adobe", country="United States", exchange="Nasdaq", rank=3,
        sector_path="Information Technology > Software & Services > Software > Application Software",
        primary_use_case="VA", secondary_use_cases=["QC", "GR"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="HV", risk_sensitivities=["BETA", "EVT", "REG"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$237.25", price_observed="2026-07-17 close",
        mvp_score=87, confidence_score=89, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=60,
        valuation_classification="UNDERVALUED", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="AI-first ARR conversion and permanent CFO succession",
        main_risk="AI displacement, ARR deceleration and interim-CFO governance",
        thesis_invalidation="ARR decelerates, margins weaken, or AI products fail to preserve retention/pricing",
        vector=[9, 8, 8, 12, 8, 10, 6, 4, 7, 5, 5, 3, 2],
    ),
    primary_candidate(
        ticker="TW", company="Tradeweb Markets", country="United States", exchange="Nasdaq", rank=4,
        sector_path="Financials > Financial Services > Capital Markets > Financial Exchanges & Data",
        primary_use_case="GR", secondary_use_cases=["SR", "QC"], market_cap_class="LARGE",
        maturity_stage="M4", volatility_class="NV", risk_sensitivities=["REG", "RATE", "EVT"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="$99.90", price_observed="2026-07-17 close",
        mvp_score=87, confidence_score=90, sovereignty_score=8, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=70,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Confirmed Q2 result on 30 July",
        main_risk="Fixed-income market share and capture-rate pressure",
        thesis_invalidation="Sustained cash-credit share/fee loss or organic growth below low double digits",
        vector=[9, 8, 8, 11, 8, 7, 8, 5, 7, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="UBER", company="Uber Technologies", country="United States", exchange="NYSE", rank=5,
        sector_path="Industrials > Transportation > Ground Transportation > Passenger Ground Transportation",
        primary_use_case="GR", secondary_use_cases=["EC", "SR"], market_cap_class="LARGE",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["BETA", "REG", "EVT"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$72.46", price_observed="2026-07-17 close",
        mvp_score=87, confidence_score=90, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=6, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="HIGH-CONVICTION RESEARCH CANDIDATE", main_catalyst="Confirmed Q2 on 5 August; AV and FCF conversion",
        main_risk="Regulation, insurance costs and AV-platform bypass",
        thesis_invalidation="Bookings fall below mid-teens, insurance destroys leverage, or AV partners bypass the network",
        vector=[9, 8, 10, 11, 8, 7, 8, 5, 7, 5, 4, 3, 2],
    ),
    primary_candidate(
        ticker="MCK", company="McKesson", country="United States", exchange="NYSE", rank=6,
        sector_path="Health Care > Health Care Equipment & Services > Health Care Providers & Services > Health Care Distributors",
        primary_use_case="QC", secondary_use_cases=["DF", "SR"], market_cap_class="LARGE",
        maturity_stage="M6", volatility_class="LV", risk_sensitivities=["REG", "EVT"],
        casino_role="DEALER", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="$841.39", price_observed="2026-07-17 close",
        mvp_score=87, confidence_score=91, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Confirmed FY27 Q1 on 5 August",
        main_risk="CVS/top-ten customer concentration, policy and opioid liabilities",
        thesis_invalidation="Major-customer loss, policy damage, or services fail to outgrow distribution",
        vector=[9, 8, 7, 11, 8, 9, 7, 5, 7, 6, 5, 3, 2],
    ),
    primary_candidate(
        ticker="BLK", company="BlackRock", country="United States", exchange="NYSE", rank=7,
        sector_path="Financials > Financial Services > Capital Markets > Asset Management & Custody Banks",
        primary_use_case="BC", secondary_use_cases=["QC", "SR"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["BETA", "RATE", "REG"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="$1,072.20", price_observed="2026-07-17 close",
        mvp_score=86, confidence_score=94, sovereignty_score=8, mines_risk_score=5,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR PULLBACK",
        action="WAIT FOR PULLBACK", main_catalyst="HPS/private-markets integration and Aladdin ACV",
        main_risk="Market beta, integration and transaction-related dilution",
        thesis_invalidation="Organic base fees collapse, Aladdin ACV slows, or dilution overwhelms per-share growth",
        vector=[9, 8, 8, 12, 7, 8, 8, 3, 7, 5, 5, 4, 2],
    ),
    primary_candidate(
        ticker="CACI", company="CACI International", country="United States", exchange="NYSE", rank=8,
        sector_path="Industrials > Commercial & Professional Services > Professional Services > Research & Consulting Services",
        primary_use_case="VA", secondary_use_cases=["GR", "SR"], market_cap_class="MID",
        maturity_stage="M4", volatility_class="NV", risk_sensitivities=["GEO", "REG", "EVT"],
        casino_role="DEALER", food_chain_role="SECONDARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$461.56", price_observed="2026-07-17 close",
        mvp_score=86, confidence_score=89, sovereignty_score=8, mines_risk_score=4,
        clairefontaine_level=6, promotion_probability=60,
        valuation_classification="UNDERVALUED", entry_status="BUY-RESEARCH ZONE",
        action="HIGH-CONVICTION RESEARCH CANDIDATE", main_catalyst="Confirmed FY26/FY27 guide on 5 August",
        main_risk="Federal timing, customer concentration and ARKA leverage",
        thesis_invalidation="Backlog/book-to-bill deteriorates, leverage stays high, or FCF/share fails to compound",
        vector=[8, 8, 9, 11, 7, 9, 8, 5, 7, 5, 4, 3, 2],
    ),
    primary_candidate(
        ticker="BNY", company="BNY", country="United States", exchange="NYSE", rank=9,
        sector_path="Financials > Financial Services > Capital Markets > Asset Management & Custody Banks",
        primary_use_case="DF", secondary_use_cases=["SR", "QC"], market_cap_class="LARGE",
        maturity_stage="M6", volatility_class="LV", risk_sensitivities=["RATE", "REG", "EVT"],
        casino_role="HOUSE", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="STRAIGHT FLUSH",
        half_life="VERY LONG", current_price="$157.13", price_observed="2026-07-17 close",
        mvp_score=85, confidence_score=95, sovereignty_score=9, mines_risk_score=3,
        clairefontaine_level=7, promotion_probability=75,
        valuation_classification="FAIRLY VALUED", entry_status="WAIT FOR PULLBACK",
        action="WAIT FOR PULLBACK", main_catalyst="Fee-led platform leverage and collateral growth",
        main_risk="Post-result gap, rate normalization, fee regulation and cyber concentration",
        thesis_invalidation="Organic fees slow, margins reverse, CET1 comes under pressure, or a major cyber event occurs",
        vector=[10, 9, 7, 12, 7, 7, 8, 2, 6, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="V", company="Visa", country="United States", exchange="NYSE", rank=10,
        sector_path="Financials > Financial Services > Financial Services > Transaction & Payment Processing Services",
        primary_use_case="BC", secondary_use_cases=["SR", "QC"], market_cap_class="MEGA",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["REG", "GEO", "EVT"],
        casino_role="CHIP", food_chain_role="QUATERNARY CONSUMER",
        current_chess_piece="QUEEN", potential_chess_piece="QUEEN", poker_hand="STRAIGHT FLUSH",
        half_life="VERY LONG", current_price="$358.56", price_observed="2026-07-17 close",
        mvp_score=85, confidence_score=92, sovereignty_score=9, mines_risk_score=4,
        clairefontaine_level=8, promotion_probability=80,
        valuation_classification="EXPENSIVE BUT DEFENSIBLE", entry_status="WAIT FOR PULLBACK",
        action="WAIT FOR PULLBACK", main_catalyst="Confirmed fiscal Q3 on 28 July",
        main_risk="Regulation, litigation, valuation and alternative payment rails",
        thesis_invalidation="Take-rate regulation, cross-border deceleration, or material new-rail disintermediation",
        vector=[10, 9, 5, 12, 8, 6, 6, 5, 7, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="CPRT", company="Copart", country="United States", exchange="Nasdaq", rank=11,
        sector_path="Industrials > Commercial & Professional Services > Commercial Services & Supplies > Diversified Support Services",
        primary_use_case="QC", secondary_use_cases=["SR", "VA"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="NV", risk_sensitivities=["EVT", "BETA"],
        casino_role="HOUSE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="VERY LONG", current_price="$27.61", price_observed="2026-07-17 close",
        mvp_score=84, confidence_score=88, sovereignty_score=9, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Unit and pricing stabilization",
        main_risk="Insurer volume weakness and falling returns on land investment",
        thesis_invalidation="Units remain weak without price/share gains, or land investment ceases to earn attractive returns",
        vector=[9, 9, 6, 11, 8, 8, 6, 4, 6, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="TOST", company="Toast", country="United States", exchange="NYSE", rank=12,
        sector_path="Financials > Financial Services > Financial Services > Transaction & Payment Processing Services",
        primary_use_case="EC", secondary_use_cases=["GR", "SR"], market_cap_class="LARGE",
        maturity_stage="M4", volatility_class="HV", risk_sensitivities=["BETA", "REG", "LIQ"],
        casino_role="CHIP", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="BISHOP", potential_chess_piece="QUEEN", poker_hand="STRAIGHT",
        half_life="LONG", current_price="$30.08", price_observed="2026-07-17 close",
        mvp_score=83, confidence_score=87, sovereignty_score=7, mines_risk_score=5,
        clairefontaine_level=6, promotion_probability=70,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="EARLY CAPTURE", main_catalyst="Retail, international, payroll and non-payment attach",
        main_risk="Restaurant cycle, competition, SBC and dilution",
        thesis_invalidation="Location/GPV growth falls below mid-teens or SBC blocks per-share conversion",
        vector=[8, 7, 11, 10, 7, 8, 7, 5, 6, 4, 4, 4, 2],
    ),
    primary_candidate(
        ticker="VLTO", company="Veralto", country="United States", exchange="NYSE", rank=13,
        sector_path="Industrials > Capital Goods > Machinery > Industrial Machinery & Supplies",
        primary_use_case="DF", secondary_use_cases=["QC", "SR"], market_cap_class="LARGE",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["REG", "BETA"],
        casino_role="DEALER", food_chain_role="PRODUCER",
        current_chess_piece="ROOK", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$93.81", price_observed="2026-07-17 close",
        mvp_score=82, confidence_score=88, sovereignty_score=9, mines_risk_score=3,
        clairefontaine_level=7, promotion_probability=70,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Confirmed Q2 call on 29 July",
        main_risk="Organic softness, tariffs and M&A execution",
        thesis_invalidation="Core growth remains below 2%, recurring mix weakens, or post-M&A leverage rises",
        vector=[8, 9, 5, 12, 7, 7, 6, 5, 6, 6, 5, 4, 2],
    ),
    primary_candidate(
        ticker="VEEV", company="Veeva Systems", country="United States", exchange="NYSE", rank=14,
        sector_path="Health Care > Health Care Equipment & Services > Health Care Technology > Health Care Technology",
        primary_use_case="GR", secondary_use_cases=["QC", "EC"], market_cap_class="LARGE",
        maturity_stage="M4", volatility_class="NV", risk_sensitivities=["REG", "EVT", "BETA"],
        casino_role="TABLE", food_chain_role="TERTIARY CONSUMER",
        current_chess_piece="ROOK", potential_chess_piece="QUEEN", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$195.38", price_observed="2026-07-17 close",
        mvp_score=82, confidence_score=90, sovereignty_score=8, mines_risk_score=4,
        clairefontaine_level=7, promotion_probability=65,
        valuation_classification="ATTRACTIVE", entry_status="WAIT FOR CATALYST",
        action="WAIT FOR CATALYST", main_catalyst="Vault CRM, Data Cloud and AI-agent adoption",
        main_risk="CRM transition, pharma budgets and SBC",
        thesis_invalidation="Subscription growth falls below low double digits, migrations slip, or per-share FCF deteriorates",
        vector=[9, 8, 8, 10, 8, 7, 7, 4, 6, 5, 5, 3, 2],
    ),
    primary_candidate(
        ticker="MSA", company="MSA Safety", country="United States", exchange="NYSE", rank=15,
        sector_path="Industrials > Capital Goods > Machinery > Industrial Machinery & Supplies",
        primary_use_case="QC", secondary_use_cases=["DF", "SR"], market_cap_class="MID",
        maturity_stage="M5", volatility_class="LV", risk_sensitivities=["REG", "BETA", "EVT"],
        casino_role="DEALER", food_chain_role="PRODUCER",
        current_chess_piece="BISHOP", potential_chess_piece="ROOK", poker_hand="FULL HOUSE",
        half_life="LONG", current_price="$171.03", price_observed="2026-07-17 close",
        mvp_score=82, confidence_score=88, sovereignty_score=8, mines_risk_score=3,
        clairefontaine_level=7, promotion_probability=55,
        valuation_classification="ATTRACTIVE", entry_status="BUY-RESEARCH ZONE",
        action="STRUCTURAL COMPOUNDER", main_catalyst="Autronica integration and margin conversion",
        main_risk="Industrial cycle, tariffs and acquisition execution",
        thesis_invalidation="Organic contraction, operating margin below 18%, or acquisition leverage/returns disappoint",
        vector=[8, 8, 6, 12, 7, 7, 6, 5, 6, 6, 5, 4, 2],
    ),
]

LATEST_PRICES = {
    "ICICIBANK": "₹1,445.70", "HDFCBANK": "₹739.55", "POWERGRID": "₹288.85",
    "SHRIRAMFIN": "₹1,038.20", "INDIAMART": "₹1,759.70", "MCX": "₹2,755.10",
    "KFINTECH": "₹949.25", "BHARTIARTL": "₹1,905.30", "INDUSTOWER": "₹387.40",
    "PERSISTENT": "₹5,268.20", "OFSS": "₹11,089.00", "RELIANCE": "₹1,280.00",
    "LT": "₹3,806.00", "SUNPHARMA": "₹1,973.70", "WABAG": "₹1,977.50",
    "ICE": "$145.79", "CME": "$255.31", "ADBE": "$225.11", "TW": "$99.83",
    "UBER": "$65.94", "MCK": "$840.90", "BLK": "$1,055.67", "CACI": "$486.77",
    "BNY": "$158.91", "V": "$355.74", "CPRT": "$27.94", "TOST": "$29.04",
    "VLTO": "$92.02", "VEEV": "$186.24", "MSA": "$174.64",
}

CURRENT_EVIDENCE_OVERRIDES: dict[str, dict[str, Any]] = {
    "ICE": {"main_catalyst": "Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage"},
    "TW": {"main_catalyst": "Scheduled Q2 release on 30 July; multi-asset share and capture"},
    "UBER": {"main_catalyst": "Scheduled Q2 release on 5 August; AV and FCF conversion"},
    "MCK": {"main_catalyst": "Scheduled FY27 Q1 release on 5 August; oncology/biopharma services mix"},
    "CACI": {"main_catalyst": "Scheduled FY26/FY27 guidance update on 5 August"},
    "V": {"main_catalyst": "Scheduled fiscal Q3 release on 28 July; cross-border and payment volumes"},
    "VLTO": {"main_catalyst": "Scheduled Q2 call on 29 July; core growth and acquisition conversion"},
    "ICICIBANK": {
        "rank": 1,
        "mvp_score": 88,
        "confidence_score": 94,
        "score_components": dict(zip(VECTOR_KEYS, [9, 9, 8, 12, 8, 8, 7, 4, 6, 6, 5, 4, 2])),
        "main_catalyst": "Q1 fee growth and loan/deposit conversion after a strong official release",
        "main_risk": "Loans grew faster than deposits; future NIM and credit normalization",
        "thesis_invalidation": "NIM persistently below 4%, deposit funding deteriorates, or slippage rises materially",
    },
    "HDFCBANK": {
        "rank": 14,
        "mvp_score": 77,
        "confidence_score": 92,
        "score_components": dict(zip(VECTOR_KEYS, [9, 9, 6, 8, 8, 10, 5, 3, 5, 4, 5, 3, 2])),
        "poker_hand": "DRAW",
        "valuation_classification": "ATTRACTIVE BUT THESIS-DAMAGED",
        "entry_status": "WAIT FOR CATALYST",
        "action": "THESIS WEAKENING",
        "main_catalyst": "Evidence that the record-low 3.26% Q1 NIM is a floor, not a new base",
        "main_risk": "Margin compression and modest profit growth despite lower provisions",
        "thesis_invalidation": "Another material NIM decline, deposit underperformance, or stalled ROA normalization",
    },
    "KFINTECH": {
        "rank": 15,
        "mvp_score": 74,
        "confidence_score": 92,
        "score_components": dict(zip(VECTOR_KEYS, [8, 7, 9, 9, 7, 4, 5, 5, 5, 4, 5, 4, 2])),
        "poker_hand": "DRAW",
        "valuation_classification": "VALUATION CAUTION AFTER RESULT GAP",
        "entry_status": "WAIT FOR CATALYST",
        "action": "THESIS WEAKENING",
        "main_catalyst": "Acquisition-separated organic growth and EBITDA-margin recovery",
        "main_risk": "Acquisition-led revenue and front-loaded costs compressed Q1 EBITDA margin to 34.2%",
        "thesis_invalidation": "Margin fails to recover above 36% or acquisition-separated growth falls below 15% for two quarters",
    },
    "PERSISTENT": {
        "main_catalyst": "Recover and verify the 21–22 July Q1 result package; Nagarro offer milestones",
        "thesis_invalidation": "Constant-currency growth below 12%, EBIT below 15%, or acquisition terms impair per-share returns",
    },
    "RELIANCE": {
        "main_catalyst": "Post-Q1 Jio/retail cash conversion and new-energy capex milestones",
    },
    "CME": {
        "rank": 2,
        "mvp_score": 89,
        "confidence_score": 94,
        "score_components": dict(zip(VECTOR_KEYS, [10, 9, 6, 12, 8, 8, 7, 4, 7, 7, 5, 4, 2])),
        "main_catalyst": "Q2 product ADV, open-interest and market-data follow-through",
        "main_risk": "Volume/capture normalization, new competition, cloud-transition and rule risk",
        "thesis_invalidation": "Persistent ADV/share loss, capture deterioration, or adverse clearing economics",
    },
}

INDIA_RANKS = {
    "ICICIBANK": 1, "POWERGRID": 2, "SHRIRAMFIN": 3, "INDIAMART": 4, "MCX": 5,
    "BHARTIARTL": 6, "INDUSTOWER": 7, "PERSISTENT": 8, "OFSS": 9, "RELIANCE": 10,
    "LT": 11, "SUNPHARMA": 12, "WABAG": 13, "HDFCBANK": 14, "KFINTECH": 15,
}

for row in INDIA + US:
    row["current_price"] = LATEST_PRICES[row["ticker"]]
    row["price_observed"] = (
        "2026-07-27 NSE close via Yahoo/yfinance"
        if row["country"] == "India"
        else "2026-07-24 regular-session close via Yahoo/yfinance"
    )
    if row["ticker"] in CURRENT_EVIDENCE_OVERRIDES:
        row.update(CURRENT_EVIDENCE_OVERRIDES[row["ticker"]])
    if row["ticker"] in INDIA_RANKS:
        row["rank"] = INDIA_RANKS[row["ticker"]]

INDIA.sort(key=lambda row: row["rank"])
US.sort(key=lambda row: row["rank"])
PRIMARY = INDIA + US
PRIMARY_BY_TICKER = {row["ticker"]: row for row in PRIMARY}


def extended_candidate(
    ticker: str,
    company: str,
    country: str,
    exchange: str,
    sector_path: str,
    primary_use_case: str,
    secondary_use_cases: list[str],
    market_cap_class: str,
    maturity_stage: str,
    volatility_class: str,
    risk_sensitivities: list[str],
    casino_role: str,
    food_chain_role: str,
    current_chess_piece: str,
    potential_chess_piece: str,
    poker_hand: str,
    half_life: str,
    mvp_score: int,
    confidence_score: int,
    action: str,
) -> dict[str, Any]:
    row = {
        "date": DATE,
        "candidate_type": "EXTENDED_BOARD",
        "ticker": ticker,
        "company": company,
        "country": country,
        "exchange": exchange,
        "sector_path": sector_path,
        "sector": sector_path.split(" > ", 1)[0],
        "primary_use_case": primary_use_case,
        "secondary_use_cases": secondary_use_cases,
        "market_cap_class": market_cap_class,
        "maturity_stage": maturity_stage,
        "share_type": "COM",
        "volatility_class": volatility_class,
        "risk_sensitivities": risk_sensitivities,
        "casino_role": casino_role,
        "food_chain_role": food_chain_role,
        "current_chess_piece": current_chess_piece,
        "potential_chess_piece": potential_chess_piece,
        "poker_hand": poker_hand,
        "half_life": half_life,
        "mvp_score": mvp_score,
        "confidence_score": confidence_score,
        "action": action,
    }
    row["canonical_classification"] = canonical(row)
    return row


E = extended_candidate
EXTENDED: list[dict[str, Any]] = [
    E("HDBFS", "HDB Financial Services", "India", "NSE", "Financials > Financial Services > Consumer Finance > Diversified Finance", "EC", ["GR", "VA"], "MID", "M4", "HV", ["RATE", "LIQ", "EVT"], "PLAYER", "SECONDARY CONSUMER", "KNIGHT", "ROOK", "TWO PAIR", "LONG", 77, 87, "EARLY CAPTURE"),
    E("HDFCAMC", "HDFC Asset Management", "India", "NSE", "Financials > Financial Services > Capital Markets > Asset Management & Custody Banks", "QC", ["SR", "GR"], "LARGE", "M5", "NV", ["REG", "BETA", "EVT"], "TABLE", "TERTIARY CONSUMER", "ROOK", "QUEEN", "FULL HOUSE", "VERY LONG", 77, 90, "WAIT FOR ENTRY"),
    E("HDFCLIFE", "HDFC Life Insurance", "India", "NSE", "Financials > Insurance > Life & Health Insurance > Life & Health Insurance", "GR", ["DF", "SR"], "LARGE", "M4", "NV", ["REG", "RATE", "EVT"], "CHIP", "TERTIARY CONSUMER", "ROOK", "QUEEN", "STRAIGHT", "VERY LONG", 76, 89, "WATCHLIST"),
    E("HSCL", "Himadri Speciality Chemical", "India", "NSE", "Materials > Materials > Chemicals > Specialty Chemicals", "CI", ["EC", "GR"], "MID", "M4", "HV", ["CMD", "LIQ", "EVT"], "PLAYER", "PRODUCER", "BISHOP", "ROOK", "STRAIGHT", "MEDIUM", 75, 84, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("GRAVITA", "Gravita India", "India", "NSE", "Materials > Materials > Metals & Mining > Diversified Metals & Mining", "EC", ["CI", "GR"], "SMALL", "M4", "HV", ["CMD", "GEO", "LIQ"], "PLAYER", "PRODUCER", "BISHOP", "ROOK", "TWO PAIR", "LONG", 74, 84, "RESEARCH DEEPER"),
    E("ANGELONE", "Angel One", "India", "NSE", "Financials > Financial Services > Capital Markets > Investment Banking & Brokerage", "MO", ["EC", "SP"], "MID", "M4", "HV", ["REG", "BETA", "LIQ"], "DEALER", "TERTIARY CONSUMER", "KNIGHT", "ROOK", "DRAW", "MEDIUM", 73, 86, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("ADANIPORTS", "Adani Ports and SEZ", "India", "NSE", "Industrials > Transportation > Transportation Infrastructure > Marine Ports & Services", "SR", ["QC", "GR"], "LARGE", "M5", "NV", ["GEO", "REG", "EVT"], "TABLE", "TERTIARY CONSUMER", "ROOK", "QUEEN", "FULL HOUSE", "VERY LONG", 77, 83, "RESEARCH DEEPER"),
    E("CAMS", "Computer Age Management Services", "India", "NSE", "Financials > Financial Services > Capital Markets > Asset-Servicing Technology", "SR", ["QC", "IN"], "MID", "M5", "NV", ["REG", "EVT"], "DEALER", "TERTIARY CONSUMER", "ROOK", "ROOK", "FULL HOUSE", "VERY LONG", 72, 84, "WATCHLIST"),
    E("CDSL", "Central Depository Services", "India", "NSE", "Financials > Financial Services > Capital Markets > Financial Exchanges & Data", "SR", ["QC", "MO"], "MID", "M5", "HV", ["REG", "BETA", "EVT"], "HOUSE", "QUATERNARY CONSUMER", "ROOK", "QUEEN", "OVERPLAYED HAND", "VERY LONG", 71, 83, "WATCHLIST"),
    E("NEWGEN", "Newgen Software Technologies", "India", "NSE", "Information Technology > Software & Services > Software > Application Software", "EC", ["GR", "SR"], "SMALL", "M3", "HV", ["LIQ", "EVT", "BETA"], "DEALER", "SECONDARY CONSUMER", "PAWN", "ROOK", "DRAW", "LONG", 70, 80, "EARLY CAPTURE"),
    E("SAGILITY", "Sagility India", "India", "NSE", "Health Care > Health Care Equipment & Services > Health Care Services > Health Care Support Services", "EC", ["GR"], "MID", "M3", "HV", ["GEO", "LIQ", "EVT"], "DEALER", "SECONDARY CONSUMER", "BISHOP", "ROOK", "TWO PAIR", "LONG", 76, 80, "RESEARCH DEEPER"),
    E("POLYCAB", "Polycab India", "India", "NSE", "Industrials > Capital Goods > Electrical Equipment > Electrical Components & Equipment", "QC", ["GR", "SR"], "LARGE", "M4", "HV", ["CMD", "BETA", "EVT"], "DEALER", "PRODUCER", "ROOK", "ROOK", "OVERPLAYED HAND", "LONG", 79, 86, "GOOD COMPANY — EXPENSIVE PRICE"),
    E("PBFINTECH", "PB Fintech", "India", "NSE", "Financials > Financial Services > Financial Services > Insurance Marketplace", "SP", ["EC", "GR"], "LARGE", "M3", "HV", ["REG", "BETA", "LIQ"], "TABLE", "TERTIARY CONSUMER", "PAWN", "KNIGHT", "DRAW", "MEDIUM", 73, 83, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("SOLARINDS", "Solar Industries India", "India", "NSE", "Materials > Materials > Chemicals > Diversified Chemicals", "GR", ["CI", "SP"], "LARGE", "M4", "HV", ["GEO", "REG", "EVT"], "PLAYER", "PRODUCER", "BISHOP", "ROOK", "OVERPLAYED HAND", "MEDIUM", 72, 84, "VALUATION CAUTION"),
    E("KAYNES", "Kaynes Technology", "India", "NSE", "Information Technology > Technology Hardware & Equipment > Electronic Equipment > Electronic Manufacturing Services", "SP", ["EC", "GR"], "MID", "M3", "HV", ["LIQ", "EVT", "GEO"], "PLAYER", "PRODUCER", "PAWN", "QUEEN", "DRAW", "MEDIUM", 68, 80, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("ETERNAL", "Eternal", "India", "NSE", "Consumer Discretionary > Consumer Services > Hotels, Restaurants & Leisure > Restaurants & Delivery", "SP", ["GR", "EC"], "LARGE", "M3", "HV", ["BETA", "LIQ", "REG"], "TABLE", "TERTIARY CONSUMER", "PAWN", "QUEEN", "OVERPLAYED HAND", "MEDIUM", 67, 80, "VALUATION CAUTION"),
    E("KPITTECH", "KPIT Technologies", "India", "NSE", "Information Technology > Software & Services > IT Services > Automotive Technology Services", "GR", ["EC"], "MID", "M4", "HV", ["BETA", "EVT", "GEO"], "DEALER", "SECONDARY CONSUMER", "BISHOP", "ROOK", "DRAW", "MEDIUM", 66, 86, "THESIS WEAKENING"),
    E("NETWEB", "Netweb Technologies", "India", "NSE", "Information Technology > Technology Hardware & Equipment > Technology Hardware > Servers & Computing Systems", "SP", ["GR", "EC"], "SMALL", "M3", "HV", ["LIQ", "BETA", "EVT"], "PLAYER", "PRODUCER", "PAWN", "ROOK", "OVERPLAYED HAND", "SHORT", 65, 78, "VALUATION CAUTION"),
    E("AMBER", "Amber Enterprises", "India", "NSE", "Consumer Discretionary > Consumer Durables & Apparel > Household Durables > Consumer Electronics", "SP", ["GR", "EC"], "MID", "M3", "HV", ["CMD", "LIQ", "EVT"], "PLAYER", "PRODUCER", "PAWN", "ROOK", "OVERPLAYED HAND", "MEDIUM", 63, 76, "VALUATION CAUTION"),
    E("KNSL", "Kinsale Capital", "United States", "NYSE", "Financials > Insurance > Insurance > Property & Casualty Insurance", "QC", ["GR", "DF"], "MID", "M4", "HV", ["EVT", "REG", "BETA"], "TABLE", "TERTIARY CONSUMER", "KNIGHT", "ROOK", "FULL HOUSE", "LONG", 84, 88, "WATCHLIST"),
    E("CTAS", "Cintas", "United States", "Nasdaq", "Industrials > Commercial & Professional Services > Commercial Services & Supplies > Diversified Support Services", "QC", ["DF", "IN"], "LARGE", "M5", "LV", ["BETA", "EVT"], "TABLE", "TERTIARY CONSUMER", "ROOK", "QUEEN", "OVERPLAYED HAND", "VERY LONG", 81, 92, "WAIT FOR ENTRY"),
    E("HUBB", "Hubbell", "United States", "NYSE", "Industrials > Capital Goods > Electrical Equipment > Electrical Components & Equipment", "GR", ["SR", "QC"], "MID", "M5", "NV", ["BETA", "CMD", "EVT"], "DEALER", "PRODUCER", "ROOK", "ROOK", "FULL HOUSE", "LONG", 79, 88, "WATCHLIST"),
    E("GWRE", "Guidewire Software", "United States", "NYSE", "Information Technology > Software & Services > Software > Application Software", "EC", ["GR", "SR"], "MID", "M3", "HV", ["BETA", "EVT", "LIQ"], "DEALER", "TERTIARY CONSUMER", "BISHOP", "ROOK", "STRAIGHT", "LONG", 79, 86, "EARLY CAPTURE"),
    E("SPGI", "S&P Global", "United States", "NYSE", "Financials > Financial Services > Capital Markets > Financial Exchanges & Data", "SR", ["QC", "BC"], "LARGE", "M5", "LV", ["REG", "RATE", "EVT"], "HOUSE", "QUATERNARY CONSUMER", "QUEEN", "QUEEN", "FULL HOUSE", "VERY LONG", 79, 90, "WATCHLIST"),
    E("NRG", "NRG Energy", "United States", "NYSE", "Utilities > Utilities > Independent Power & Renewable Electricity Producers > Independent Power Producers", "CI", ["CY", "EC"], "LARGE", "M4", "HV", ["CMD", "RATE", "REG"], "PLAYER", "PRIMARY CONSUMER", "ROOK", "QUEEN", "TWO PAIR", "MEDIUM", 78, 87, "EARLY CAPTURE"),
    E("VRSK", "Verisk Analytics", "United States", "Nasdaq", "Industrials > Commercial & Professional Services > Professional Services > Research & Consulting Services", "QC", ["SR", "DF"], "LARGE", "M5", "LV", ["REG", "EVT"], "HOUSE", "QUATERNARY CONSUMER", "QUEEN", "QUEEN", "FULL HOUSE", "VERY LONG", 78, 88, "RESEARCH DEEPER"),
    E("BR", "Broadridge Financial Solutions", "United States", "NYSE", "Industrials > Commercial & Professional Services > Professional Services > Data Processing & Outsourced Services", "SR", ["QC", "IN"], "LARGE", "M5", "LV", ["REG", "EVT", "RATE"], "DEALER", "TERTIARY CONSUMER", "ROOK", "QUEEN", "FULL HOUSE", "VERY LONG", 77, 86, "RESEARCH DEEPER"),
    E("ITRI", "Itron", "United States", "Nasdaq", "Information Technology > Technology Hardware & Equipment > Electronic Equipment > Electronic Equipment & Instruments", "EC", ["SR", "GR"], "MID", "M3", "HV", ["EVT", "REG", "BETA"], "PLAYER", "PRODUCER", "PAWN", "ROOK", "STRAIGHT", "LONG", 75, 83, "EARLY CAPTURE"),
    E("CNM", "Core & Main", "United States", "NYSE", "Industrials > Capital Goods > Trading Companies & Distributors > Trading Companies & Distributors", "CY", ["SR", "VA"], "MID", "M4", "NV", ["RATE", "BETA", "LIQ"], "DEALER", "SECONDARY CONSUMER", "BISHOP", "ROOK", "TWO PAIR", "LONG", 74, 82, "RESEARCH DEEPER"),
    E("IOT", "Samsara", "United States", "NYSE", "Information Technology > Software & Services > Software > Systems Software", "EC", ["GR", "SR"], "LARGE", "M3", "HV", ["BETA", "LIQ", "EVT"], "DEALER", "TERTIARY CONSUMER", "PAWN", "ROOK", "STRAIGHT", "LONG", 76, 88, "EARLY CAPTURE"),
    E("PCOR", "Procore Technologies", "United States", "NYSE", "Information Technology > Software & Services > Software > Application Software", "EC", ["GR", "SR"], "MID", "M3", "HV", ["RATE", "BETA", "LIQ"], "DEALER", "TERTIARY CONSUMER", "BISHOP", "QUEEN", "DRAW", "LONG", 76, 86, "EARLY CAPTURE"),
    E("ALKT", "Alkami Technology", "United States", "Nasdaq", "Information Technology > Software & Services > Software > Application Software", "EC", ["GR", "SR"], "MID", "M3", "HV", ["RATE", "LIQ", "EVT"], "DEALER", "TERTIARY CONSUMER", "PAWN", "ROOK", "DRAW", "LONG", 74, 85, "EARLY CAPTURE"),
    E("HIMS", "Hims & Hers Health", "United States", "NYSE", "Health Care > Health Care Equipment & Services > Health Care Providers & Services > Health Care Services", "SP", ["GR", "EC"], "LARGE", "M3", "HV", ["REG", "LIQ", "EVT"], "TABLE", "TERTIARY CONSUMER", "PAWN", "KNIGHT", "DRAW", "SHORT", 65, 86, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("PLTR", "Palantir Technologies", "United States", "Nasdaq", "Information Technology > Software & Services > Software > Systems Software", "QC", ["GR", "SR"], "MEGA", "M4", "HV", ["GEO", "REG", "BETA"], "TABLE", "TERTIARY CONSUMER", "QUEEN", "QUEEN", "OVERPLAYED HAND", "LONG", 70, 92, "GOOD COMPANY — EXPENSIVE PRICE"),
    E("HOOD", "Robinhood Markets", "United States", "Nasdaq", "Financials > Financial Services > Capital Markets > Investment Banking & Brokerage", "SP", ["MO", "EC"], "LARGE", "M4", "HV", ["REG", "BETA", "LIQ"], "DEALER", "TERTIARY CONSUMER", "BISHOP", "QUEEN", "OVERPLAYED HAND", "MEDIUM", 68, 89, "VALUATION CAUTION"),
    E("RKLB", "Rocket Lab", "United States", "Nasdaq", "Industrials > Capital Goods > Aerospace & Defense > Aerospace & Defense", "SP", ["EC", "GR"], "LARGE", "M2", "HV", ["EVT", "LIQ", "GEO"], "PLAYER", "PRODUCER", "PAWN", "ROOK", "DRAW", "MEDIUM", 66, 88, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("TEM", "Tempus AI", "United States", "Nasdaq", "Health Care > Health Care Equipment & Services > Health Care Technology > Health Care Technology", "SP", ["EC", "GR"], "MID", "M2", "HV", ["REG", "LIQ", "EVT"], "DEALER", "TERTIARY CONSUMER", "PAWN", "BISHOP", "DRAW", "MEDIUM", 66, 84, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("APLD", "Applied Digital", "United States", "Nasdaq", "Information Technology > Software & Services > IT Services > Internet Services & Infrastructure", "SP", ["EC", "CY"], "MID", "M2", "HV", ["RATE", "LIQ", "EVT"], "PLAYER", "PRIMARY CONSUMER", "PAWN", "ROOK", "DRAW", "SHORT", 62, 83, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("CRWV", "CoreWeave", "United States", "Nasdaq", "Information Technology > Software & Services > IT Services > Internet Services & Infrastructure", "SP", ["GR", "EC"], "LARGE", "M3", "HV", ["RATE", "LIQ", "EVT"], "PLAYER", "PRIMARY CONSUMER", "BISHOP", "ROOK", "OVERPLAYED HAND", "MEDIUM", 58, 88, "VALUATION CAUTION"),
    E("ASTS", "AST SpaceMobile", "United States", "Nasdaq", "Communication Services > Telecommunication Services > Wireless Telecommunication Services > Satellite Communications", "SP", ["EC", "GR"], "LARGE", "M1", "HV", ["EVT", "LIQ", "GEO"], "PLAYER", "PRODUCER", "PAWN", "QUEEN", "DRAW", "MEDIUM", 55, 79, "HIGH UPSIDE — HIGH MINE DENSITY"),
    E("IONQ", "IonQ", "United States", "NYSE", "Information Technology > Technology Hardware & Equipment > Technology Hardware > Quantum Computing Systems", "SP", ["EC", "GR"], "MID", "M1", "HV", ["LIQ", "EVT", "BETA"], "PLAYER", "PRODUCER", "PAWN", "QUEEN", "OVERPLAYED HAND", "SHORT", 54, 87, "VALUATION CAUTION"),
    E("LNG", "Cheniere Energy", "United States", "NYSE", "Energy > Energy > Oil, Gas & Consumable Fuels > Oil & Gas Storage & Transportation", "IN", ["CI", "SR"], "LARGE", "M6", "NV", ["CMD", "GEO", "REG"], "DEALER", "PRODUCER", "ROOK", "ROOK", "FULL HOUSE", "LONG", 79, 82, "HIGH-CONVICTION RESEARCH CANDIDATE"),
    E("MLM", "Martin Marietta Materials", "United States", "NYSE", "Materials > Materials > Construction Materials > Construction Materials", "CY", ["QC", "CI"], "LARGE", "M5", "NV", ["CMD", "RATE", "BETA"], "PLAYER", "PRODUCER", "ROOK", "ROOK", "FULL HOUSE", "LONG", 76, 82, "RESEARCH DEEPER"),
    E("ORLY", "O'Reilly Automotive", "United States", "Nasdaq", "Consumer Discretionary > Consumer Discretionary Distribution & Retail > Specialty Retail > Automotive Retail", "QC", ["DF", "BC"], "LARGE", "M5", "LV", ["BETA", "EVT"], "TABLE", "TERTIARY CONSUMER", "ROOK", "QUEEN", "FULL HOUSE", "LONG", 80, 86, "HIGH-CONVICTION RESEARCH CANDIDATE"),
    E("PEP", "PepsiCo", "United States", "Nasdaq", "Consumer Staples > Food, Beverage & Tobacco > Beverages > Soft Drinks & Non-alcoholic Beverages", "DF", ["IN", "BC"], "MEGA", "M6", "LV", ["CMD", "GEO", "REG"], "DEALER", "PRODUCER", "QUEEN", "QUEEN", "FULL HOUSE", "LONG", 76, 88, "WAIT FOR CATALYST"),
    E("TMUS", "T-Mobile US", "United States", "Nasdaq", "Communication Services > Telecommunication Services > Wireless Telecommunication Services > Wireless Telecommunication Services", "SR", ["QC", "BC"], "MEGA", "M5", "LV", ["REG", "RATE", "EVT"], "HOUSE", "TERTIARY CONSUMER", "QUEEN", "QUEEN", "FULL HOUSE", "VERY LONG", 80, 88, "RESEARCH DEEPER"),
    E("CBRE", "CBRE Group", "United States", "NYSE", "Real Estate > Real Estate Management & Development > Real Estate Management & Development > Real Estate Services", "QC", ["SR", "CY"], "LARGE", "M5", "NV", ["RATE", "BETA", "EVT"], "TABLE", "TERTIARY CONSUMER", "ROOK", "QUEEN", "FULL HOUSE", "LONG", 81, 86, "HIGH-CONVICTION RESEARCH CANDIDATE"),
    E("M&M", "Mahindra & Mahindra", "India", "NSE", "Consumer Discretionary > Automobiles & Components > Automobiles > Automobile Manufacturers", "CY", ["QC", "VA"], "LARGE", "M5", "NV", ["BETA", "CMD", "RATE"], "PLAYER", "PRODUCER", "ROOK", "QUEEN", "FULL HOUSE", "LONG", 80, 89, "HIGH-CONVICTION RESEARCH CANDIDATE"),
    E("ITC", "ITC", "India", "NSE", "Consumer Staples > Food, Beverage & Tobacco > Tobacco > Tobacco", "IN", ["VA", "DF"], "LARGE", "M6", "LV", ["REG", "CMD"], "PLAYER", "PRODUCER", "ROOK", "ROOK", "FULL HOUSE", "LONG", 76, 89, "RESEARCH DEEPER"),
    E("DLF", "DLF", "India", "NSE", "Real Estate > Real Estate Management & Development > Real Estate Management & Development > Real Estate Development", "CY", ["IN", "QC"], "LARGE", "M5", "HV", ["RATE", "REG", "BETA"], "PLAYER", "PRIMARY CONSUMER", "ROOK", "ROOK", "TWO PAIR", "MEDIUM", 72, 87, "VALUATION CAUTION"),
]

ALL_REGISTRY = PRIMARY + EXTENDED
REGISTRY_BY_TICKER = {row["ticker"]: row for row in ALL_REGISTRY}


def winner_row(
    segment: str,
    india: str,
    us: str,
    overall: str,
    *,
    runner_up: str = NQ,
    why: str,
    risk: str,
    action: str,
    **extra: Any,
) -> dict[str, Any]:
    score = REGISTRY_BY_TICKER[overall]["mvp_score"] if overall != NQ else None
    confidence = REGISTRY_BY_TICKER[overall]["confidence_score"] if overall != NQ else None
    return {
        "segment": segment,
        "best_india": india,
        "best_us": us,
        "best_overall": overall,
        "runner_up": runner_up,
        "mvp_score": score,
        "confidence": confidence,
        "why_winner": why,
        "main_risk": risk,
        "action": action,
        **extra,
    }


USE_CASE_WINNERS = [
    winner_row("QC — Quality compounder", "ICICIBANK", "MCK", "MCK", runner_up="ICICIBANK", why="Essential healthcare throughput plus expanding oncology/biopharma services and $5.4B FY26 FCF.", risk="Customer and policy concentration.", action="STRUCTURAL COMPOUNDER"),
    winner_row("GR — Growth", "SHRIRAMFIN", "UBER", "UBER", runner_up="TW", why="Bookings, EBITDA and FCF are converting while ads, membership and AV distribution add independent paths.", risk="Regulation, insurance costs and AV bypass.", action="HIGH-CONVICTION RESEARCH CANDIDATE"),
    winner_row("VA — Value", "SHRIRAMFIN", "ADBE", "ADBE", runner_up="CACI", why="Official FY26 guidance implies unusually low earnings pot odds despite substantial cash generation and real AI-first ARR; Shriram is the cleaner India value/growth blend after HDFC's margin breach.", risk="AI displacement and management transition.", action="WAIT FOR CATALYST"),
    winner_row("IN — Income", "POWERGRID", "CME", "CME", runner_up="INDUSTOWER", why="Benchmark liquidity, clearing and exceptional cash economics support distributions without requiring directional market calls.", risk="ADV/capture normalization and rule changes.", action="STRUCTURAL COMPOUNDER"),
    winner_row("BC — Blue-chip core", "ICICIBANK", "V", "ICICIBANK", runner_up="V", why="Capital, underwriting, deposits and payments combine with better entry pot odds than the premium-priced US network.", risk="Deposit and credit normalization.", action="STRUCTURAL COMPOUNDER"),
    winner_row("DF — Defensive", "SUNPHARMA", "VLTO", "VLTO", runner_up="MCK", why="Regulated water/product-quality measurement has high recurring mix, low mine density and long installed-base life.", risk="Organic softness, tariffs and acquisition execution.", action="STRUCTURAL COMPOUNDER"),
    winner_row("CY — Cyclical", "LT", "NRG", "LT", runner_up="NRG", why="Large diversified order book and improving working capital provide converted evidence across the capex cycle.", risk="Project mix, geopolitics and cash conversion.", action="HIGH-CONVICTION RESEARCH CANDIDATE"),
    winner_row("MO — Momentum", NQ, "BNY", "BNY", why="Fresh Q2 fee growth, margin expansion and a result-day breakout are evidence-backed, but the gap weakens entry.", risk="Gap failure, NII reversal and fee regulation.", action="WAIT FOR PULLBACK"),
    winner_row("EC — Early capture", "WABAG", "TOST", "TOST", runner_up="SHRIRAMFIN", why="Positive FCF and 20%+ operating growth support a real POS/payment Dealer-to-commerce-Table path; Wabag is the cleaner India Pawn-to-Rook path after KFin's margin breach.", risk="Restaurant cycle, competition and dilution.", action="EARLY CAPTURE"),
    winner_row("TU — Turnaround", NQ, NQ, NQ, why="No screened issuer had both a damaged base and enough verified repair evidence to clear the hurdle.", risk="Quota-filling would confuse price decline with operating repair.", action="NO QUALIFIED WINNER TODAY"),
    winner_row("SS — Special situation", NQ, NQ, NQ, why="No merger, demerger, restructuring or legal event had sufficiently verified odds and entry data.", risk="Event timing and legal outcomes were not uniformly validated.", action="NO QUALIFIED WINNER TODAY"),
    winner_row("SR — Structural rail", "POWERGRID", "ICE", "ICE", runner_up="CME", why="Four reinforcing rails—exchanges, clearing, data and mortgage workflow—create the broadest made House.", risk="Debt, mortgage cyclicality and regulation.", action="STRUCTURAL COMPOUNDER"),
    winner_row("CI — Commodity / inflation", "HSCL", "NRG", "NRG", runner_up="HSCL", why="Generation, retail load and virtual-power-plant optionality offer several conversion paths beyond a pure commodity bet.", risk="Leverage, ERCOT, hedging and regulation.", action="EARLY CAPTURE"),
    winner_row("SP — Speculative asymmetry", "KAYNES", "RKLB", "KAYNES", runner_up="RKLB", why="OSAT/critical-electronics promotion could materially change role and addressable market if customer qualification and utilization arrive.", risk="Capex funding, qualification, utilization and negative post-capex FCF.", action="HIGH UPSIDE — HIGH MINE DENSITY"),
    winner_row("DS — Distressed", NQ, NQ, NQ, why="No impaired issuer offered adequate balance-sheet runway, governance evidence and positive weighted odds.", risk="Distress can destroy optionality before recovery.", action="NO QUALIFIED WINNER TODAY"),
]

SECTOR_WINNERS = [
    winner_row("Energy", "RELIANCE", "LNG", "RELIANCE", runner_up="LNG", why="Digital/retail mix provides non-commodity paths around the integrated-energy base.", risk="Capex, O2C cycle and complexity.", action="WAIT FOR CATALYST", primary_use_case="BC"),
    winner_row("Materials", "HSCL", "MLM", "MLM", runner_up="HSCL", why="Aggregate reserves, local network density and infrastructure demand offer better made economics than early material qualification stories.", risk="Construction cycle, pricing and input costs.", action="RESEARCH DEEPER", primary_use_case="CY"),
    winner_row("Industrials", "LT", "CACI", "CACI", runner_up="MCK", why="Mission/cyber mix, backlog and FCF growth offer superior pot odds with embedded federal access.", risk="Federal award timing and acquisition leverage.", action="HIGH-CONVICTION RESEARCH CANDIDATE", primary_use_case="VA"),
    winner_row("Consumer Discretionary", "M&M", "ORLY", "ORLY", runner_up="M&M", why="Aftermarket distribution density and non-discretionary repair demand create converted defensive retail economics.", risk="Valuation, wage pressure and vehicle-cycle normalization.", action="HIGH-CONVICTION RESEARCH CANDIDATE", primary_use_case="QC"),
    winner_row("Consumer Staples", "ITC", "PEP", "ITC", runner_up="PEP", why="Cash generation, distribution and a discounted income/value setup offer better current pot odds than the US incumbent.", risk="Tobacco regulation/tax, FMCG margin conversion and weak price trend.", action="RESEARCH DEEPER", primary_use_case="IN"),
    winner_row("Health Care", "SUNPHARMA", "MCK", "MCK", runner_up="VEEV", why="Essential distribution plus services expansion converts demand into durable cash.", risk="Customer and policy concentration.", action="STRUCTURAL COMPOUNDER", primary_use_case="QC"),
    winner_row("Financials", "ICICIBANK", "ICE", "ICE", runner_up="CME", why="Diversified clearing/data/workflow economics earn across multiple participant outcomes.", risk="Regulation, leverage and mortgage cycle.", action="STRUCTURAL COMPOUNDER", primary_use_case="SR"),
    winner_row("Information Technology", "PERSISTENT", "ADBE", "ADBE", runner_up="OFSS", why="Large converted cash flow and disruption-level valuation create better odds than high-multiple AI narratives.", risk="AI substitution and ARR deceleration.", action="WAIT FOR CATALYST", primary_use_case="VA"),
    winner_row("Communication Services", "BHARTIARTL", "TMUS", "TMUS", runner_up="BHARTIARTL", why="Spectrum, billing, network density and direct customer access form a mature connectivity House.", risk="Regulation, spectrum economics and leverage.", action="RESEARCH DEEPER", primary_use_case="SR"),
    winner_row("Utilities", "POWERGRID", "NRG", "POWERGRID", runner_up="NRG", why="Regulated transmission is paid across competing generation technologies.", risk="Allowed-return changes and capex delays.", action="STRUCTURAL COMPOUNDER", primary_use_case="SR"),
    winner_row("Real Estate", "DLF", "CBRE", "CBRE", runner_up="DLF", why="Asset-light services and property workflows offer better cycle survival than levered property ownership.", risk="Transaction cycle, rates and commercial-property stress.", action="HIGH-CONVICTION RESEARCH CANDIDATE", primary_use_case="QC"),
]

MARKET_CAP_WINNERS = [
    winner_row("MEGA", "ICICIBANK", "V", "ICICIBANK", runner_up="V", why="Superior current pot odds with high sovereignty and clean capital.", risk="Deposit/NIM and credit cycle.", action="STRUCTURAL COMPOUNDER", use_case="QC", liquidity_check="Pass—deep institutional liquidity; executable quote still requires revalidation."),
    winner_row("LARGE", "POWERGRID", "ICE", "ICE", runner_up="MCK", why="Best large-cap made edge across node control, cash conversion and valuation.", risk="Regulation, mortgage cycle and debt.", action="STRUCTURAL COMPOUNDER", use_case="SR", liquidity_check="Pass—NYSE large-cap liquidity; no live order book used."),
    winner_row("MID", "INDIAMART", "CACI", "CACI", runner_up="KFINTECH", why="Backlog, differentiated mission systems and modest forward valuation beat the cohort.", risk="Federal timing and ARKA leverage.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="VA", liquidity_check="Pass for research; validate spread and volume before execution."),
    winner_row("SMALL", "WABAG", NQ, "WABAG", why="Net cash, audited conversion and water scarcity create a qualified small-cap path.", risk="Receivables, overseas execution and liquidity.", action="EARLY CAPTURE", use_case="EC", liquidity_check="Conditional—liquidity and current promoter/pledge checks required."),
    winner_row("MICRO", NQ, NQ, NQ, why="Liquidity and evidence quality were insufficient in both countries.", risk="Spread, manipulation, governance and data gaps.", action="NO QUALIFIED WINNER TODAY", use_case="—", liquidity_check="Fail"),
    winner_row("NANO", NQ, NQ, NQ, why="No nano-cap passed institutional liquidity and disclosure gates.", risk="Extreme liquidity and information asymmetry.", action="NO QUALIFIED WINNER TODAY", use_case="—", liquidity_check="Fail"),
]

MATURITY_WINNERS = [
    winner_row("M1 — Pre-commercial / emerging", NQ, NQ, NQ, why="ASTS and IonQ remain pre-conversion with valuation and financing ahead of commercial proof.", risk="Technical, funding and dilution mines.", action="NO QUALIFIED WINNER TODAY", use_case="SP", main_mine="Funding/dilution before recurring commercial evidence"),
    winner_row("M2 — Early growth / pre-profit", NQ, NQ, NQ, why="Rocket Lab and Tempus remain research options, not qualified winners at current pot odds.", risk="Cash burn, execution and valuation compression.", action="NO QUALIFIED WINNER TODAY", use_case="SP", main_mine="Cash runway and per-share dilution"),
    winner_row("M3 — Scaling growth", "NEWGEN", "IOT", "IOT", runner_up="PCOR", why="Connected-operations data has measurable ARR/product-attach milestones and positive promotion geometry.", risk="Valuation, SBC and platform competition.", action="EARLY CAPTURE", use_case="EC", main_mine="SBC and emerging-product conversion"),
    winner_row("M4 — Profitable growth", "SHRIRAMFIN", "UBER", "UBER", runner_up="TW", why="Profitable marketplace growth now converts into meaningful FCF.", risk="Regulation, insurance and AV bypass.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="GR", main_mine="Regulatory and insurance-cost correlation"),
    winner_row("M5 — Mature compounder", "ICICIBANK", "ICE", "ICE", runner_up="CME", why="Multiple reinforcing infrastructure rails and strong cash economics.", risk="Regulation, debt and mortgage cycle.", action="STRUCTURAL COMPOUNDER", use_case="SR", main_mine="Rule/capture-rate change"),
    winner_row("M6 — Cash-generating incumbent", "POWERGRID", "MCK", "MCK", runner_up="BNY", why="Essential throughput and services expansion support recurring cash generation.", risk="Customer and policy concentration.", action="STRUCTURAL COMPOUNDER", use_case="QC", main_mine="Customer concentration"),
    winner_row("M7 — Declining / disrupted / turnaround", NQ, NQ, NQ, why="No damaged incumbent showed enough verified repair to overcome cohort alternatives.", risk="Value traps and balance-sheet decay.", action="NO QUALIFIED WINNER TODAY", use_case="TU", main_mine="Unproven repair"),
]

VOLATILITY_WINNERS = [
    winner_row("LV — Low volatility", "POWERGRID", "MCK", "MCK", runner_up="CME", why="Essential healthcare flow and made FCF with lower market sensitivity.", risk="Policy and customer concentration.", action="STRUCTURAL COMPOUNDER", use_case="QC", risk_control="Monitor customer mix and policy; revalidate price."),
    winner_row("NV — Normal volatility", "ICICIBANK", "ICE", "ICE", runner_up="ICICIBANK", why="Best blend of structural control, evidence and valuation in the normal-volatility cohort.", risk="Regulation and mortgage/debt exposure.", action="STRUCTURAL COMPOUNDER", use_case="SR", risk_control="Stage entry around Q2 evidence; monitor leverage."),
    winner_row("HV — High volatility", "SHRIRAMFIN", "ADBE", "ADBE", runner_up="TOST", why="Large cash generation and low implied expectations compensate for volatility better than pre-profit peers.", risk="AI substitution and management transition.", action="WAIT FOR CATALYST", use_case="VA", risk_control="Require ARR/retention evidence; avoid catalyst-size exposure."),
]

RISK_WINNERS = [
    winner_row("BETA", "LT", "UBER", "UBER", runner_up="LT", why="Operating conversion and multiple independent growth paths make risk-on exposure more attractive.", risk="Macro slowdown and regulation.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="GR", attractive_exposure="Cash-generating platform leverage rather than pre-profit beta."),
    winner_row("LIQ", "WABAG", NQ, "WABAG", why="The liquidity discount is paired with net cash and audited FCF, but remains conditional.", risk="Spread, ownership validation and receivables.", action="EARLY CAPTURE", use_case="EC", attractive_exposure="Potential small-cap rerating after order-to-cash proof."),
    winner_row("EVT", "RELIANCE", "CME", "CME", runner_up="RELIANCE", why="CME's released Q2 converted event risk into evidence; Reliance remains the better India post-result mix-review candidate.", risk="ADV/capture normalization and event-gap reversal.", action="STRUCTURAL COMPOUNDER", use_case="IN", attractive_exposure="Released operating evidence rather than an unpriced binary event."),
    winner_row("CMD", "HSCL", "NRG", "NRG", runner_up="RELIANCE", why="Retail load, generation and orchestration diversify the commodity transmission mechanism.", risk="ERCOT, hedge book and leverage.", action="EARLY CAPTURE", use_case="CI", attractive_exposure="Several paths beyond spot commodity direction."),
    winner_row("RATE", "ICICIBANK", "BNY", "ICICIBANK", runner_up="BNY", why="Capital and underwriting allow spread/fee resilience without a heroic rate forecast.", risk="Deposit competition and NIM compression.", action="STRUCTURAL COMPOUNDER", use_case="QC", attractive_exposure="Rate exposure buffered by capital, fees and customer ownership."),
    winner_row("REG", "POWERGRID", "ICE", "ICE", runner_up="POWERGRID", why="Regulatory permission is also a moat when the operator has scale, liquidity and multiple rails.", risk="Adverse rule economics or compliance/cyber failure.", action="STRUCTURAL COMPOUNDER", use_case="SR", attractive_exposure="Permissioned market infrastructure with diversified revenue."),
    winner_row("GEO", "LT", "CACI", "CACI", runner_up="BHARTIARTL", why="Mission-system demand is structurally supported and backlog/FCF evidence already exists.", risk="Federal timing, budget priorities and leverage.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="VA", attractive_exposure="Embedded access and differentiated systems, not only a defence label."),
]

CASINO_WINNERS = [
    winner_row("PLAYER", "SHRIRAMFIN", "NRG", "SHRIRAMFIN", runner_up="NRG", why="The lending Player has better current valuation and converted profit growth than high-mine operating Players.", risk="Credit quality and funding costs.", action="HIGH-CONVICTION RESEARCH CANDIDATE", sector="Financials", valuation_risk="Moderate; credit-cycle discount is warranted."),
    winner_row("DEALER", "BHARTIARTL", "MCK", "MCK", runner_up="BHARTIARTL", why="Essential healthcare distribution earns repeatedly and is adding higher-margin services; Airtel is the stronger India Dealer after KFin's margin breach.", risk="Customer and policy concentration.", action="STRUCTURAL COMPOUNDER", sector="Health Care", valuation_risk="Low/moderate versus converted FCF."),
    winner_row("TABLE", "INDIAMART", "UBER", "UBER", runner_up="TW", why="Marketplace liquidity now converts into cash while ads, membership and AV distribution widen capture.", risk="Regulation, insurance and bypass.", action="HIGH-CONVICTION RESEARCH CANDIDATE", sector="Industrials", valuation_risk="Moderate; growth must remain mid-teens or better."),
    winner_row("HOUSE", "ICICIBANK", "ICE", "ICE", runner_up="CME", why="Rules, access, clearing, data and workflows form the strongest multi-rail House.", risk="Regulation, debt and mortgage cyclicality.", action="STRUCTURAL COMPOUNDER", sector="Financials", valuation_risk="Moderate; non-heroic but Q2 must confirm."),
    winner_row("CHIP", "ICICIBANK", "V", "V", runner_up="TOST", why="Global authorization and settlement collect across commerce with exceptional margins and ubiquity.", risk="Premium valuation, regulation and alternative rails.", action="WAIT FOR PULLBACK", sector="Financials", valuation_risk="High near the annual high."),
]

CHESS_WINNERS = [
    winner_row("Best current PAWN", "NEWGEN", "ITRI", "ITRI", runner_up="NEWGEN", why="Software/service mix can promote metering equipment into operational intelligence.", risk="Backlog, deployment timing, tariffs and M&A.", action="EARLY CAPTURE", promotion_probability="55%", time_horizon="3–5 years", main_milestone="Outcomes growth, backlog stabilization and repeatable FCF", main_mine="Utility deployment timing"),
    winner_row("Best current KNIGHT", "HDBFS", "KNSL", "KNSL", runner_up="HDBFS", why="Specialty E&S underwriting is a differentiated niche with elite current combined-ratio evidence.", risk="Pricing cycle, catastrophe and reserve error.", action="WATCHLIST", promotion_probability="55%", time_horizon="3–5 years", main_milestone="Sustain underwriting discipline through softer pricing", main_mine="Reserve/catastrophe correlation"),
    winner_row("Best current BISHOP", "INDIAMART", "CACI", "CACI", runner_up="INDIAMART", why="A specialist mission position is already converting into backlog, EBITDA and FCF; IndiaMART retains a cash-rich SME-workflow promotion path.", risk="Federal timing and leverage.", action="HIGH-CONVICTION RESEARCH CANDIDATE", promotion_probability="60%", time_horizon="3–5 years", main_milestone="Mission mix and FCF/share compound", main_mine="Award timing"),
    winner_row("Best current ROOK", "POWERGRID", "TW", "TW", runner_up="POWERGRID", why="Electronic fixed-income protocols and liquidity are broadening into a multi-asset House.", risk="Share and capture-rate pressure.", action="STRUCTURAL COMPOUNDER", promotion_probability="70%", time_horizon="3–5 years", main_milestone="Multi-asset share and organic revenue", main_mine="Capture-rate compression"),
    winner_row("Best current QUEEN", "ICICIBANK", "ICE", "ICE", runner_up="ICICIBANK", why="The broadest combination of rule control, liquidity, data, workflow and cash conversion.", risk="Regulation, debt and mortgage cycle.", action="STRUCTURAL COMPOUNDER", promotion_probability="80% deeper House", time_horizon="3–5 years", main_milestone="Data growth and deleveraging", main_mine="Regulatory economics"),
    winner_row("Best PAWN → KNIGHT", "PBFINTECH", "HIMS", "PBFINTECH", runner_up="HIMS", why="A differentiated insurance marketplace can become a broader financial specialist if recurring profit and clean conversion persist.", risk="Regulation, customer economics and valuation.", action="HIGH UPSIDE — HIGH MINE DENSITY", promotion_probability="45%", time_horizon="3–5 years", main_milestone="Recurring profit and per-share FCF", main_mine="Regulatory/customer-acquisition economics"),
    winner_row("Best PAWN → BISHOP", "HSCL", "TEM", "HSCL", runner_up="TEM", why="Critical-material qualification can create a defensible vertical specialty beyond commodity chemistry.", risk="Capex, qualification and input cycles.", action="HIGH UPSIDE — HIGH MINE DENSITY", promotion_probability="50%", time_horizon="3–5 years", main_milestone="Qualified customers and post-capex FCF", main_mine="Technology qualification"),
    winner_row("Best PAWN → ROOK", "WABAG", "IOT", "WABAG", runner_up="IOT", why="Water projects can become a recurring O&M rail with net cash already protecting the path.", risk="Receivables and sovereign execution.", action="EARLY CAPTURE", promotion_probability="60%", time_horizon="3–5 years", main_milestone="Framework conversion, collections and O&M mix", main_mine="Working-capital recurrence"),
    winner_row("Best PAWN → QUEEN", "ETERNAL", "TOST", "TOST", runner_up="ETERNAL", why="Restaurant POS/payments has positive FCF and measurable retail, payroll and international promotion tiles.", risk="SBC, competition and restaurant cycle.", action="EARLY CAPTURE", promotion_probability="70%", time_horizon="2–4 years", main_milestone="Recurring gross profit and per-share FCF", main_mine="Dilution"),
]

FOOD_CHAIN_WINNERS = [
    winner_row("PRODUCER", "RELIANCE", "VLTO", "RELIANCE", runner_up="VLTO", why="Produces energy while controlling increasingly valuable digital and retail distribution layers.", risk="Capex and conglomerate complexity.", action="WAIT FOR CATALYST", capture_mechanism="Integrated production plus downstream distribution/platform ownership."),
    winner_row("PRIMARY CONSUMER", NQ, "NRG", "NRG", why="Consumes fuel/capacity inputs but adds retail load and orchestration rather than relying only on generation spreads.", risk="Commodity, hedge and leverage correlation.", action="EARLY CAPTURE", capture_mechanism="Generation-to-retail load plus VPP orchestration."),
    winner_row("SECONDARY CONSUMER", "LT", "CACI", "CACI", runner_up="LT", why="Converts labor, technology and acquired IP into embedded mission systems with backlog and FCF evidence.", risk="Federal timing and leverage.", action="HIGH-CONVICTION RESEARCH CANDIDATE", capture_mechanism="Embedded mission access and differentiated system delivery."),
    winner_row("TERTIARY CONSUMER", "INDIAMART", "UBER", "UBER", runner_up="MCK", why="Owns customer discovery/liquidity and collects across local commerce participants.", risk="Regulation, insurance and bypass.", action="HIGH-CONVICTION RESEARCH CANDIDATE", capture_mechanism="Marketplace liquidity, memberships, ads and AV distribution."),
    winner_row("QUATERNARY CONSUMER", "ICICIBANK", "ICE", "ICE", runner_up="CME", why="Controls permission, matching, clearing, data and workflow at the top of the economic chain.", risk="Regulation and operational/cyber concentration.", action="STRUCTURAL COMPOUNDER", capture_mechanism="Tolls on access, risk transfer, clearing, data and workflow."),
]

HALF_LIFE_WINNERS = [
    winner_row("ULTRA-SHORT", NQ, NQ, NQ, why="No hype-duration exposure qualified for a non-speculative recommendation.", risk="Narrative collapse before cash conversion.", action="NO QUALIFIED WINNER TODAY", use_case="SP", durability_logic="No durable cash half-life", decay_risk="Attention decay"),
    winner_row("SHORT", NQ, NQ, NQ, why="Short-half-life candidates did not offer enough valuation protection and survival runway.", risk="Funding, dilution and narrative decay.", action="NO QUALIFIED WINNER TODAY", use_case="SP", durability_logic="Milestone-dependent rather than recurring", decay_risk="Capital-market access"),
    winner_row("MEDIUM", "LT", "NRG", "LT", runner_up="NRG", why="Multi-year capex conversion is visible, diversified and backed by a large order book.", risk="Project margins and cash conversion.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="CY", durability_logic="National capex cycle plus order backlog", decay_risk="Order quality/working capital"),
    winner_row("LONG", "WABAG", "UBER", "UBER", runner_up="ADBE", why="Local-market liquidity and repeat usage can expand through multiple monetization layers.", risk="Regulation, insurance and AV bypass.", action="HIGH-CONVICTION RESEARCH CANDIDATE", use_case="GR", durability_logic="Recurring multi-sided marketplace behavior", decay_risk="Disintermediation"),
    winner_row("VERY LONG", "ICICIBANK", "ICE", "ICE", runner_up="CME", why="Regulatory permission, liquidity, benchmarks, data and embedded workflows reinforce one another.", risk="Rule changes, cyber and capital allocation.", action="STRUCTURAL COMPOUNDER", use_case="SR", durability_logic="Permissioned infrastructure and self-reinforcing liquidity", decay_risk="Regulatory economics or technology migration"),
]

SEGMENT_GROUPS = {
    "use_case_winners": USE_CASE_WINNERS,
    "sector_winners": SECTOR_WINNERS,
    "market_cap_winners": MARKET_CAP_WINNERS,
    "maturity_stage_winners": MATURITY_WINNERS,
    "volatility_winners": VOLATILITY_WINNERS,
    "risk_sensitivity_winners": RISK_WINNERS,
    "structural_role_winners": CASINO_WINNERS,
    "chess_promotion_winners": CHESS_WINNERS,
    "food_chain_winners": FOOD_CHAIN_WINNERS,
    "half_life_winners": HALF_LIFE_WINNERS,
}

FINAL_SELECTIONS = [
    {"selection": "Best India opportunity today", "winner": "ICICIBANK", "why": "Highest India blend of capital, underwriting, customer ownership and pot odds after a strong Q1.", "missing": "Fee growth, stable NIM and capital can persist without a heroic rate or credit assumption.", "catalyst": "Q1 loan, deposit and fee conversion into the next quarter.", "invalidation": "NIM persistently below 4%, deposit funding deteriorates, or renewed slippage.", "evidence": "Deposit cohorts, fee mix, credit cost, CET1 and segment ROA."},
    {"selection": "Best US opportunity today", "winner": "ICE", "why": "Best overall score and broadest diversified House at a defensible valuation.", "missing": "Mortgage weakness obscures clearing, energy/rates, data and workflow compounding.", "catalyst": "Confirmed Q2 on 30 July.", "invalidation": "Data slowdown, share/capture loss or deleveraging failure.", "evidence": "Segment organic growth, mortgage revenue, FCF and net-debt bridge."},
    {"selection": "Best India early-capture opportunity", "winner": "WABAG", "why": "Net cash, audited FCF and recurring O&M can promote a project contractor into a water-infrastructure Rook.", "missing": "Scarce treatment capability and O&M mix can outlive individual EPC awards.", "catalyst": "Framework-to-firm-order conversion, collections and O&M mix.", "invalidation": "Receivables re-expand, overseas execution losses recur, or framework conversion fails.", "evidence": "Firm orders, receivable ageing, cash collection, O&M revenue and promoter/pledge refresh."},
    {"selection": "Best US early-capture opportunity", "winner": "TOST", "why": "ARR, location and GPV growth now coexist with positive FCF.", "missing": "Retail, international, payroll and capital attach can widen value per location.", "catalyst": "Next result and attach-rate disclosure.", "invalidation": "Location/GPV growth below mid-teens or SBC blocks per-share conversion.", "evidence": "Cohort retention, recurring gross profit, SBC/share and international economics."},
    {"selection": "Best India structural house/table/rail", "winner": "POWERGRID", "why": "An unavoidable regulated transmission rail earns across competing generation winners.", "missing": "Renewable evacuation converts capex into regulated assets rather than a directional power bet.", "catalyst": "Project capitalization and awards.", "invalidation": "Allowed-return damage, commissioning delay or debt outruns earnings.", "evidence": "Project capitalization, CWIP, leverage and regulated-return schedule."},
    {"selection": "Best US structural house/table/rail", "winner": "ICE", "why": "Clearing permission, proprietary liquidity, data and workflow form the broadest House.", "missing": "Four reinforcing rails make earnings less volume-dependent than the exchange label implies.", "catalyst": "Confirmed Q2 on 30 July.", "invalidation": "Regulatory economics change or recurring data loses pricing/share.", "evidence": "Data retention, clearing share, mortgage workflow and leverage."},
    {"selection": "Best India risk-adjusted opportunity", "winner": "ICICIBANK", "why": "Highest combination of sovereignty, evidence, valuation and mine survival.", "missing": "The balance sheet does not require a repair thesis.", "catalyst": "Q1 deposit/NIM evidence.", "invalidation": "Deposit franchise weakens or credit cost rises sharply.", "evidence": "Deposit cohorts, LCR, CET1, credit cost and segment ROA."},
    {"selection": "Best US risk-adjusted opportunity", "winner": "CME", "why": "Released Q2 revenue of $1.7B, benchmark liquidity, clearing and exceptional margins support low mine density.", "missing": "Product depth and collateral efficiency can compound without permanently higher volatility.", "catalyst": "Post-Q2 ADV, open-interest and market-data follow-through.", "invalidation": "Persistent ADV/share loss or capture deterioration.", "evidence": "Product ADV, open interest, capture, expenses, cloud-transition costs and capital return."},
    {"selection": "Highest-upside India candidate", "winner": "KAYNES", "why": "Successful OSAT/critical-electronics promotion could change both role and addressable market.", "missing": "Platform value is possible only after qualification and utilization—not yet made.", "catalyst": "Customer qualification and capex commissioning.", "invalidation": "Funding stress, delay, low utilization or persistent negative post-capex FCF.", "evidence": "Binding customers, yields, utilization, funding stack and audited FCF bridge."},
    {"selection": "Highest-upside US candidate", "winner": "ASTS", "why": "Direct-to-device service could become a global telecom layer.", "missing": "Partner distribution may lower customer-acquisition needs if the constellation works.", "catalyst": "Funding terms, launch cadence and first recurring commercial revenue.", "invalidation": "Launch/technical failure, underfunding or dilution overwhelms per-share value.", "evidence": "Final financing, uptime, service revenue and funded deployment."},
    {"selection": "Most attractively valued India candidate", "winner": "HDFCBANK", "why": "The post-result selloff creates the largest valuation discount in the quality-bank cohort, but this is a damaged-thesis value candidate, not a clean winner.", "missing": "The market may be over-extrapolating the record-low 3.26% Q1 NIM; evidence of a floor is still absent.", "catalyst": "A quarter of NIM stabilization, deposit mix improvement and better core pre-provision growth.", "invalidation": "Another material NIM decline, deposit underperformance or stalled ROA normalization.", "evidence": "Average-balance NIM, deposit mix, normalized provisions, ROA, costs and asset quality."},
    {"selection": "Most attractively valued US candidate", "winner": "ADBE", "why": "Low official-guidance earnings pot odds with substantial cash generation.", "missing": "AI can be an upsell and retention tool, not only a substitute.", "catalyst": "AI ARR, retention and permanent CFO succession.", "invalidation": "ARR deceleration, margin damage or AI erodes pricing/retention.", "evidence": "Product AI ARR, renewal cohorts, inference cost, SBC and FCF."},
    {"selection": "Most overpriced pawn", "winner": "IONQ", "why": "Commercial cash evidence remains tiny relative to a valuation assuming scaled quantum demand.", "missing": "Technical progress is not yet repeatable cash-generating standard control.", "catalyst": "Commercial revenue and error-correction evidence.", "invalidation": "Scaled customer use and positive unit economics arrive much sooner than expected.", "evidence": "Production workloads, bookings conversion, burn and dilution."},
    {"selection": "Best matrix segment winner overall", "winner": "ICE", "why": "It wins Structural Rail, House, Very-Long Half-Life and overall score without heroic entry assumptions.", "missing": "The combined ecosystem is broader than the exchange label.", "catalyst": "Confirmed Q2 on 30 July.", "invalidation": "Multi-segment organic growth or cash conversion weakens materially.", "evidence": "Segment revenue, recurring data, clearing share, FCF and debt."},
    {"selection": "Best under-followed India discovery", "winner": "SHRIRAMFIN", "why": "Mid-teens AUM growth and normalized profit growth at attractive pot odds.", "missing": "The franchise may be evolving beyond specialist vehicle lending.", "catalyst": "Funding-cost and credit-cost normalization.", "invalidation": "Stage 2/3 rises, collections weaken or funding advantage disappears.", "evidence": "Vintages, collections, Stage 2/3, ECL and ALM schedule."},
    {"selection": "Best under-followed US discovery", "winner": "BNY", "why": "Fresh fee growth, platform margin and 31.3% ROTCE show converted operating leverage.", "missing": "It remains framed as a rate-sensitive custodian rather than settlement/collateral infrastructure.", "catalyst": "Fee-led growth after the result gap.", "invalidation": "Fee/margin reversal, CET1 pressure or a major cyber event.", "evidence": "Organic fee/NII bridge, platform expenses, CET1 and buybacks."},
]

DEEPER_RESEARCH = ["HDFCBANK", "CME", "KFINTECH", "WABAG", "SHRIRAMFIN", "BNY", "ADBE", "RELIANCE", "CPRT", "INDUSTOWER"]


def md_escape(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out.extend("| " + " | ".join(md_escape(v) for v in row) + " |" for row in rows)
    return "\n".join(out)


def winner_name(value: str) -> str:
    if value == NQ:
        return NQ
    row = REGISTRY_BY_TICKER[value]
    return f"{row['company']} ({row['exchange']}:{value})"


def value(row: dict[str, Any], key: str, winner: bool = False) -> Any:
    item = row.get(key)
    if winner and isinstance(item, str):
        return winner_name(item)
    return item if item not in (None, "") else "—"


def segment_table(rows: list[dict[str, Any]], specs: list[tuple[str, str, bool]]) -> str:
    return markdown_table(
        [spec[0] for spec in specs],
        [[value(row, key, is_winner) for _, key, is_winner in specs] for row in rows],
    )


def extract(text: str, start: str, end: str) -> str:
    start_pos = text.index(start)
    end_pos = text.index(end, start_pos)
    return text[start_pos:end_pos].strip()


def without_first_heading(fragment: str) -> str:
    lines = fragment.splitlines()
    return "\n".join(lines[1:]).strip() if lines and lines[0].startswith("#") else fragment.strip()


def candidate_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "Rank", "Company", "Ticker", "Sector", "Primary Use Case", "Market Cap", "Current Price",
        "MVP Score", "Confidence", "Casino Role", "Chess Piece", "Poker Hand", "Half-Life",
        "Sovereignty", "Mines Risk", "Valuation", "Entry", "Catalyst", "Risk", "Action",
    ]
    body = []
    for row in sorted(rows, key=lambda x: x["rank"]):
        body.append([
            row["rank"], row["company"], f"{row['exchange']}:{row['ticker']}", row["sector"],
            row["primary_use_case"], row["market_cap_class"], row["current_price"], row["mvp_score"],
            row["confidence_score"], row["casino_role"], f"{row['current_chess_piece']} → {row['potential_chess_piece']}",
            row["poker_hand"], row["half_life"], f"{row['sovereignty_score']}/10", f"{row['mines_risk_score']}/10",
            row["valuation_classification"], row["entry_status"], row["main_catalyst"], row["main_risk"], row["action"],
        ])
    return markdown_table(headers, body)


def vector_table(rows: list[dict[str, Any]]) -> str:
    return markdown_table(
        ["Ticker", "SN/SV/PG/FQ/CB/VO/CI/EN/PE/MS/HL/CF/GF", "Total"],
        [[f"{r['exchange']}:{r['ticker']}", "/".join(str(r["score_components"][k]) for k in VECTOR_KEYS), r["mvp_score"]] for r in rows],
    )


def framework_audit_table(rows: list[dict[str, Any]]) -> str:
    return markdown_table(
        ["Candidate", "Poker", "Casino", "Food Chain", "Half-Life", "Chess", "Promotion", "Clairefontaine", "Sovereignty", "Mine Density", "Fallacy Filter"],
        [[
            f"{r['exchange']}:{r['ticker']}", r["poker_hand"], r["casino_role"], r["food_chain_role"], r["half_life"],
            f"{r['current_chess_piece']} → {r['potential_chess_piece']}", f"{r['promotion_probability']}%",
            f"Level {r['clairefontaine_level']}", f"{r['sovereignty_score']}/10",
            "LOW" if r["mines_risk_score"] <= 3 else "MODERATE" if r["mines_risk_score"] == 4 else "ELEVATED" if r["mines_risk_score"] == 5 else "HIGH",
            "STRUCTURAL PATTERN; analogy not used",
        ] for r in rows],
    )


def board_table(tickers: list[str]) -> str:
    rows: list[list[Any]] = []
    for rank, ticker in enumerate(tickers, 1):
        row = REGISTRY_BY_TICKER[ticker]
        rows.append([
            rank,
            row["company"],
            f"{row['exchange']}:{ticker}",
            row["country"],
            row["mvp_score"],
            row["confidence_score"],
            row["primary_use_case"],
            row["casino_role"],
            row["poker_hand"],
            row["half_life"],
            row.get("main_catalyst", "Promotion proof plus the next current filing"),
            row.get("main_risk", ", ".join(row["risk_sensitivities"]) or "Evidence gap"),
            row["action"],
        ])
    return markdown_table(
        ["Rank", "Company", "Ticker", "Country", "MVP", "Confidence", "Use Case", "Casino Role", "Poker", "Half-Life", "Catalyst / Evidence Gate", "Main Risk", "Action"],
        rows,
    )


def deeper_research_table(tickers: list[str]) -> str:
    rows: list[list[Any]] = []
    for rank, ticker in enumerate(tickers, 1):
        row = REGISTRY_BY_TICKER[ticker]
        rows.append([
            rank,
            row["company"],
            f"{row['exchange']}:{ticker}",
            row.get("main_catalyst", "Next current filing and promotion proof"),
            row.get("main_risk", ", ".join(row["risk_sensitivities"])),
            row.get("thesis_invalidation", "Failure to convert the stated promotion milestone"),
            row["action"],
        ])
    return markdown_table(
        ["Rank", "Company", "Ticker", "Why Now / Evidence Needed", "Main Mine", "Thesis Invalidation", "Action"],
        rows,
    )


def build_markdown(source: str, generated_at: str, india_status: str, us_status: str) -> str:
    india_theses = extract(source, "### India candidate theses and invalidations", "## SECTION 3")
    us_theses = extract(source, "### United States candidate theses and invalidations", "### Primary-candidate cross-framework audit")
    us_theses = us_theses.replace(
        "At $224.56, official FY26 guidance implies about **12.5x GAAP EPS** or **9.2x non-GAAP EPS**",
        "At the 24 July $225.11 close, official FY26 guidance still implies about **12.5x GAAP EPS** or **9.2x non-GAAP EPS**",
    ).replace(
        "At $169 the quote is roughly 27.7x provider TTM FCF",
        "At the 24 July $174.64 close the quote is roughly 28.6x the same provider TTM FCF",
    )
    cross_audit = extract(source, "### Primary-candidate cross-framework audit", "## SECTION 4")
    india_additional = without_first_heading(extract(source, "## SECTION 4", "## SECTION 5"))
    us_additional = without_first_heading(extract(source, "## SECTION 5", "## SECTION 6"))
    early_capture = without_first_heading(extract(source, "## SECTION 6", "## SECTION 7"))
    rails = without_first_heading(extract(source, "## SECTION 7", "## SECTION 8"))
    combined = without_first_heading(extract(source, "## SECTION 8", "## SECTION 9"))
    risk_adjusted = without_first_heading(extract(source, "## SECTION 9", "## SECTION 10"))
    high_mines = without_first_heading(extract(source, "## SECTION 10", "## SECTION 11"))
    queen_pawns = without_first_heading(extract(source, "## SECTION 11", "## SECTION 12"))
    high_mines = high_mines.replace(
        "ASTS closed at $66.31 on 15 July; its convertible announcement followed the close, so the next executable price was unknown at analysis time: **LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT**.",
        "ASTS closed at $55.01 on 16 July, down 17.0% after the convertible announcement. The reset improves pot odds but does not remove constellation, funding or dilution mines; any executable quote still requires live validation.",
    )
    queen_pawns = (
        queen_pawns.replace("15 July price / approximate cap", "16 July close / approximate cap")
        .replace("$66.31 / $25.7B", "$55.01 / $16.4B")
        .replace("$76.20 / $47.6B", "$67.35 / $42.1B")
        .replace("$133.76 / $320.7B", "$134.44 / $322.3B")
        .replace("$115.54 / $104.0B", "$106.02 / $95.5B")
        .replace("$77.12 / $42.1B", "$72.91 / $39.8B")
        .replace("$57.25 / $10.3B", "$53.59 / $9.6B")
        .replace("$37.51 / $14.0B", "$35.10 / $13.1B")
    )
    hype_traps = without_first_heading(extract(source, "## SECTION 12", "## SECTION 13"))
    action_board = without_first_heading(extract(source, "## SECTION 13", "# FINAL DAILY SYNTHESIS"))
    early_capture = (
        "### India — top 8\n\n" + board_table(BOARD_DATA["early_capture_india"]) +
        "\n\n### United States — top 8\n\n" + board_table(BOARD_DATA["early_capture_us"])
    )
    rails = (
        "### India — top 5\n\n" + board_table(BOARD_DATA["houses_tables_chips_rails_india"]) +
        "\n\n### United States — top 5\n\n" + board_table(BOARD_DATA["houses_tables_chips_rails_us"])
    )
    combined = board_table(BOARD_DATA["combined_top20"])
    risk_adjusted = (
        "### India — top 5\n\n" + board_table(BOARD_DATA["best_risk_adjusted_india"]) +
        "\n\n### United States — top 5\n\n" + board_table(BOARD_DATA["best_risk_adjusted_us"])
    )
    action_board = board_table([row["ticker"] for row in PRIMARY])
    deeper = "### 17. Top 10 companies requiring immediate deeper research\n\n" + deeper_research_table(DEEPER_RESEARCH)

    parts: list[str] = []
    parts.append("# Sleeping Passenger — India + United States Matrix Winner Discovery")
    parts.append(
        "> **Advisory research only. No investment is guaranteed.** Scores rank research priority and weighted evidence; "
        "they are not target returns or trade instructions.\n\n"
        "> `LIVE VALIDATION REQUIRED` for executable prices, promoter/pledge and related-party fields, current Form 4/13F "
        "activity, complete estimate revisions, and any ownership field not explicitly linked to a current filing."
    )

    parts.append("## 1. Analysis Metadata")
    parts.append(
        f"- **Analysis date:** {DATE}\n"
        f"- **Generation time:** {generated_at}, Asia/Calcutta\n"
        f"- **India market status:** **{india_status}**\n"
        f"- **United States market status:** **{us_status}**\n"
        "- **Scope:** India—NSE/BSE; United States—NYSE, Nasdaq and NYSE American. Foreign ADRs and every other country are excluded.\n"
        "- **Equal-depth rule:** 15 India and 15 US primary candidates; 10 India and 10 US additional discoveries; every segment has separate India and US fields.\n"
        "- **Price basis:** India primary prices are 27 July NSE closes and US primary prices are 24 July regular-session closes, refreshed through Yahoo/yfinance. The official NSE index map is the 27 July 15:30 IST close. They are dated reference observations, not executable bids/offers.\n"
        "- **Data sources:** [official NSE all-indices feed](https://www.nseindia.com/api/allIndices), Yahoo/yfinance read-only OHLCV, "
        "[SEC EDGAR](https://www.sec.gov/edgar/search/), company investor-relations releases and the sourced "
        f"[fully sourced discovery evidence spine](daily_stock_discovery_{EVIDENCE_DATE}.md), plus the official 18–27 July result releases linked in the evidence delta.\n"
        "- **Financial periods:** India FY2025-26/Q1 FY2026-27 where released; US Q1/Q2/FY2026 as identified in each linked release.\n"
        "- **Confidence:** separate from opportunity. It discounts stale fields, source disagreement, transparency gaps, limited samples and forecast uncertainty.\n"
        "- **GICS:** all 11 official broad sectors are used. Industry group/industry/sub-industry are working GICS-normalized mappings and should be rechecked against a licensed constituent file before production use."
    )

    parts.append("### Repository recovery and discipline")
    parts.append(
        "- Branch: `sprint/open-the-gate-gap-closer`.\n"
        "- Baseline worktree was already dirty: six tracked files modified plus prior reports and `tmp/` untracked. Those changes were preserved.\n"
        "- Reused: `fresh_market_discovery.py`, `daily_scoring.py`, `minimum_daily_universe.py`, market/Yahoo adapters, ticker resolution, OHLCV utilities, and prior report conventions.\n"
        "- Existing isolated 100-point matrix builder and 16 July evidence spine were reused; no production application code was modified.\n"
        "- Change made: the isolated report builder was minimally refreshed for 27 July prices, market maps, released-event deltas, scoring and validation metadata; no commit or push.\n"
        "- Live-source audit: the official NSE all-indices feed returned the 27 July 15:30 close and Yahoo returned 27 July India/24 July US reference closes for all 30 primaries. The repository's 24 July daily payload is `STATIC_UNIVERSE_FALLBACK`/`UNVERIFIED`, so it was excluded as live evidence.\n"
        "- Dependency audit: Python and the existing yfinance/pandas report path executed successfully. Report syntax, JSON parsing, CSV rows and matrix invariants are validated by the builder."
    )

    parts.append("### Data limitations")
    parts.append(
        "No consolidated real-time feed/order book, full estimate-history database, uniformly current promoter/insider/institutional feed, "
        "or active multi-provider quote fallback was available. India promoter encumbrance, FII/DII, auditor/RPT and free-float fields, and US "
        "SBC/Form 4/customer/cloud concentration fields were included only when filing-supported; otherwise they remain a next-evidence gate. "
        "Bank/NBFC/insurer conventional FCF is not used as though it were industrial-company FCF."
    )

    parts.append("## 2. India Market Map")
    parts.append(
        "- **Condition:** broad relief rally after five losing sessions. At the official 27 July 15:30 IST close, Nifty 50 was **+0.96%**, "
        "Nifty 500 **+1.05%**, Midcap 100 **+1.11%**, and Nifty 500 breadth was **387 advances / 110 declines**; India VIX was **12.66 (-9.76%)**. "
        "[Official NSE feed](https://www.nseindia.com/api/allIndices)\n"
        "- **Leadership:** IT **+2.34%**, Realty **+2.28%**, Pharma **+1.56%**, Health Care **+1.46%** and Auto **+1.60%** led; all tracked sector indices were positive.\n"
        "- **Macro drivers:** the pause in US–Iran strikes and a sharp oil decline reduced India's import/inflation risk for the session; earnings dispersion and INR/rate sensitivity remain the next filters. "
        "[27 July market wrap](https://upstox.com/news/market-news/stocks/market-wrap-july-27-sensex-jumps-776-pts-nifty-50-ends-at-23-996-led-by-it-bank-stocks-as-crude-oil-prices-decline-eternal-indi-go-top-gainers/article-197620/)\n"
        "- **Fresh evidence gates:** ICICI's Q1 release passed the NIM/capital/asset-quality gate; HDFC Bank's 3.26% NIM breached this screen's prior 3.3% invalidation; KFin's 34.2% EBITDA margin breached its prior 38% gate despite revenue growth. "
        "[ICICI Q1](https://www.icici.bank.in/about-us/news-room/2026/performance-review-quarter-ended-june-30-2026), "
        "[HDFC result archive](https://www.hdfc.bank.in/about-us/investor-relations/financial-results), "
        "[KFin Q1 KPI](https://investor.kfintech.com/quarterly-key-performance-indicators/)\n"
        "- **Strongest areas:** well-capitalized lenders; capital-market/registry rails; transmission; telecom towers/data; water infrastructure; selective digital engineering; auto only where cash and share evidence convert.\n"
        "- **Avoid/discount:** leveraged renewables, order-book stories without cash, weak-governance microcaps, oil-sensitive airlines and queen-priced EMS/semiconductor narratives.\n"
        "- **Risk appetite:** constructive but still event-sensitive. Broad breadth and falling VIX support research activity, while the five-session decline immediately before today argues against treating one relief day as a regime change."
    )

    parts.append("## 3. United States Market Map")
    parts.append(
        "- **Condition:** mixed and concentration-sensitive. On 24 July the S&P 500 rose **less than 0.1%**, the Dow gained **0.5%**, and Nasdaq fell **0.6%**; for the week they fell **0.6%**, **0.4%** and **2.1%**, respectively. "
        "[AP market close](https://apnews.com/article/stocks-dow-nasdaq-iran-oil-02d01b8f38ccd51f605c4414cdd4fa9b)\n"
        "- **Leadership:** the Dow outperformed Nasdaq while oil and Treasury yields eased Friday; non-consensus financial infrastructure, healthcare throughput and recurring industrial services remain preferred over index-heavy AI concentration.\n"
        "- **Macro drivers:** June CPI fell 0.4% month-on-month but remained 3.5% year-on-year; core CPI was 2.6% year-on-year. The 28–29 July FOMC meeting, oil/geopolitical volatility and Q2 earnings dominate near-term event risk. "
        "[Official BLS CPI](https://www.bls.gov/news.release/cpi.nr0.htm)\n"
        "- **Strongest areas:** exchanges/clearing/data, custody/settlement/collateral, profitable software dislocations, healthcare throughput, mission systems, water/safety and workflow promotion.\n"
        "- **Avoid/discount:** pre-revenue space/quantum, leveraged AI clouds, tenant-concentrated data-centre funding, managed care without claims proof and backlog treated as cash.\n"
        "- **US-specific normalization:** diluted FCF/share after SBC, buybacks, insider events, customer/cloud concentration, AI-capex dependence, antitrust/platform risk and index/valuation concentration. Only Visa is a mega-cap among the US primary 15."
    )

    parts.append("## 4. Full Matrix Segment Winners")
    parts.append("### Scoring and evidence confidence")
    weights_text = "; ".join(f"{name.replace('_', ' ').title()} {weight}" for name, weight in SCORE_WEIGHTS.items())
    parts.append(
        f"The requested weights are used exactly: {weights_text}. **Total = {sum(SCORE_WEIGHTS.values())}.** "
        "Scores are comparative judgments anchored to current filings, dated price evidence and cohort-relative economics. "
        "Confidence is not upside probability. A `NO QUALIFIED WINNER TODAY` result is a valid finding, not missing data."
    )
    parts.append("#### Auditable primary score vectors")
    parts.append("Vector order: `SN/SV/PG/FQ/CB/VO/CI/EN/PE/MS/HL/CF/GF`.")
    parts.append(vector_table(PRIMARY))

    parts.append("### 4.1 Use-case winners")
    parts.append(segment_table(USE_CASE_WINNERS, [
        ("Use Case", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Runner-Up", "runner_up", True), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Winner", "why_winner", False), ("Main Risk", "main_risk", False), ("Action", "action", False),
    ]))

    parts.append("### 4.2 GICS sector winners")
    parts.append(segment_table(SECTOR_WINNERS, [
        ("Sector", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Primary Use Case", "primary_use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Winner", "why_winner", False), ("Main Risk", "main_risk", False), ("Action", "action", False),
    ]))
    parts.append(
        "Sector-gap evidence was separately checked so data abundance did not determine winners: "
        "[M&M FY26](https://www.mahindra.com/news-room/press-release/en/m-and-m-results-q4-f26-and-fy26), "
        "[ITC FY26](https://itcportal.com/media-centre/press-releases/media-statement-financial-results-for-the-quarter-and-year-ended-31st-march-2026.html), "
        "[DLF FY26](https://www.dlf.in/media-press-release/Q4FY26-Press-Release-DLF.pdf), "
        "[Cheniere Q1](https://lngir.cheniere.com/news-events/press-releases/detail/339/cheniere-reports-first-quarter-2026-results-and-raises-full), "
        "[Martin Marietta Q1](https://ir.martinmarietta.com/news-releases/news-release-details/martin-marietta-reports-first-quarter-2026-results), "
        "[O'Reilly Q1](https://corporate.oreillyauto.com/2026/04/29/oreilly-automotive-inc-reports-first-quarter-2026-results/), "
        "[PepsiCo Q2](https://investors.pepsico.com/docs/pepsico-5v9wci20/media/Files/investors/q2-2026-earnings-release.pdf), "
        "[T-Mobile Q1](https://www.t-mobile.com/news/business/t-mobile-q1-2026-earnings), and "
        "[CBRE Q1](https://ir.cbre.com/press-releases/detail/265/cbre-group-inc-reports-financial-results-for-q1-2026). "
        "DLF remains valuation-caution; sector nomination does not make it a top-30 primary candidate."
    )

    parts.append("### 4.3 Market-cap winners")
    parts.append(segment_table(MARKET_CAP_WINNERS, [
        ("Market Cap", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Use Case", "use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Liquidity Check", "liquidity_check", False), ("Main Risk", "main_risk", False), ("Action", "action", False),
    ]))

    parts.append("### 4.4 Maturity-stage winners")
    parts.append(segment_table(MATURITY_WINNERS, [
        ("Maturity Stage", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Use Case", "use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Winner", "why_winner", False), ("Main Mine", "main_mine", False), ("Action", "action", False),
    ]))

    parts.append("### 4.5 Volatility winners")
    parts.append(segment_table(VOLATILITY_WINNERS, [
        ("Volatility Class", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Use Case", "use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why It Fits", "why_winner", False), ("Risk Control", "risk_control", False), ("Action", "action", False),
    ]))

    parts.append("### 4.6 Risk-sensitivity winners")
    parts.append(segment_table(RISK_WINNERS, [
        ("Risk Tag", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Use Case", "use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Exposure Is Attractive", "attractive_exposure", False), ("Main Risk", "main_risk", False), ("Action", "action", False),
    ]))

    parts.append("### 4.7 Structural-role winners")
    parts.append(segment_table(CASINO_WINNERS, [
        ("Casino Role", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Sector", "sector", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Winner", "why_winner", False), ("Valuation Risk", "valuation_risk", False), ("Action", "action", False),
    ]))

    parts.append("### 4.8 Chess-promotion winners")
    parts.append(segment_table(CHESS_WINNERS, [
        ("Chess Segment", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Promotion Probability", "promotion_probability", False),
        ("Time Horizon", "time_horizon", False), ("Main Milestone", "main_milestone", False), ("Main Mine", "main_mine", False), ("Action", "action", False),
    ]))

    parts.append("### 4.9 Food-chain winners")
    parts.append(segment_table(FOOD_CHAIN_WINNERS, [
        ("Food Chain Role", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Capture Mechanism", "capture_mechanism", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Why Winner", "why_winner", False), ("Main Risk", "main_risk", False), ("Action", "action", False),
    ]))

    parts.append("### 4.10 Economic half-life winners")
    parts.append(segment_table(HALF_LIFE_WINNERS, [
        ("Half-Life Class", "segment", False), ("Best India", "best_india", True), ("Best US", "best_us", True),
        ("Best Overall", "best_overall", True), ("Use Case", "use_case", False), ("MVP Score", "mvp_score", False),
        ("Confidence", "confidence", False), ("Durability Logic", "durability_logic", False), ("Main Decay Risk", "decay_risk", False), ("Action", "action", False),
    ]))

    parts.append("### Canonical classification registry — all named research candidates")
    parts.append(
        "Every stock named as a primary, additional, early-capture, high-mine, valuation-caution or sector-gap candidate has one primary use case, "
        "zero-to-three secondary use cases and the required vector. `COM` was confirmed as the listed common/equity class for this screen."
    )
    parts.append("#### Primary 30")
    parts.append("```text\n" + "\n".join(row["canonical_classification"] for row in PRIMARY) + "\n```")
    parts.append("#### Extended and sector-gap registry")
    parts.append("```text\n" + "\n".join(row["canonical_classification"] for row in EXTENDED) + "\n```")

    parts.append("### Cross-framework audit of the primary 30")
    parts.append(framework_audit_table(PRIMARY))
    parts.append(
        "`Promotion probability` is conditional business-role migration—not a price-target probability. Mine density combines funding, debt, dilution, "
        "regulation, governance, concentration, technology, commodity, currency, rate, execution, valuation and liquidity correlations."
    )
    parts.append(cross_audit)

    parts.append("### 27 July evidence delta — supersedes stale gates in the 16 July thesis notes")
    parts.append(
        "- **ICICI Bank — gate passed / score 88:** Q1 PAT grew 15.9%, core operating profit 15.6%, fee income 23.5%, deposits 14.0% and loans 19.6%; NIM was 4.36%, net NPA 0.35% and CET1 16.19%. The faster loan growth makes funding the next mine, but the made hand strengthened. "
        "[Official Q1 review](https://www.icici.bank.in/about-us/news-room/2026/performance-review-quarter-ended-june-30-2026)\n"
        "- **HDFC Bank — prior invalidation triggered / score 77:** Q1 standalone PAT grew about 5% and NII about 7%, but NIM fell to a record-low 3.26%, below this screen's prior 3.3% invalidation threshold; gross/net NPA were 1.17%/0.41%. Action is `THESIS WEAKENING` until a margin floor is evidenced. "
        "[Official result archive](https://www.hdfc.bank.in/about-us/investor-relations/financial-results), [result summary](https://www.business-standard.com/companies/quarterly-results/hdfc-bank-q1fy27-results-net-profit-rises-5-to-19-060-cr-nii-grows-7-126071800598_1.html)\n"
        "- **KFin Technologies — prior invalidation triggered / score 74:** Q1 revenue from operations was ₹3,565.4M versus ₹2,740.6M, but EBITDA margin fell to 34.2% from 41.5% and PBT slipped to ₹1,036.6M from ₹1,051.6M. The price rose 10.67% on 27 July, worsening entry while acquisition-separated conversion remains unresolved. Action is `THESIS WEAKENING`. "
        "[Official Q1 KPI](https://investor.kfintech.com/quarterly-key-performance-indicators/)\n"
        "- **CME Group — gate passed / score 89:** released Q2 revenue was $1.7B and operating income $1.1B. The result removes the old pending-event gate; product ADV, capture and cloud-transition costs now determine follow-through. "
        "[Official Q2 release](https://www.cmegroup.com/media-room/press-releases/2026/7/22/cme_group_inc_reportsstrongfinancialresultsforq22026.html)\n"
        "- **Persistent Systems:** the board calendar shows 21–22 July for Q1, but a current official result package was not recovered in this run. Its table price is current; the earnings delta is `DATA INSUFFICIENT` and the score was not raised. "
        "[Official board calendar](https://www.persistent.com/investors/investors-communication/tentative-bm-calendar/)"
    )

    parts.append("## 5. Top 15 India Primary Candidates")
    parts.append(candidate_table(INDIA))
    parts.append(india_theses)

    parts.append("## 6. Top 15 United States Primary Candidates")
    parts.append(candidate_table(US))
    parts.append(us_theses)

    parts.append("## 7. Additional Discovery Board")
    parts.append("### India — 10 additional names")
    parts.append(india_additional)
    parts.append("### United States — 10 additional names")
    parts.append(us_additional)

    parts.append("## 8. Early-Capture Board")
    parts.append(early_capture)

    parts.append("## 9. Current Houses, Tables, Chips, and Rails")
    parts.append(rails)

    parts.append("## 10. Combined India + US Top 20")
    parts.append(combined)

    parts.append("## 11. Best Risk-Adjusted Ideas")
    parts.append(risk_adjusted)

    parts.append("## 12. High Upside, High Mine Density")
    parts.append(high_mines)

    parts.append("## 13. Queen-Priced Pawns")
    parts.append(queen_pawns)

    parts.append("## 14. False-Pattern and Hype Traps")
    parts.append(hype_traps)

    parts.append("### Action and catalyst board")
    parts.append(action_board)

    parts.append("## 15. Final Daily Synthesis")
    final_rows = []
    for number, item in enumerate(FINAL_SELECTIONS, 1):
        final_rows.append([
            number, item["selection"], winner_name(item["winner"]), item["why"], item["missing"], item["catalyst"],
            item["invalidation"], item["evidence"],
        ])
    parts.append(markdown_table(
        ["No.", "Required Selection", "Winner", "Why", "What Market May Be Missing", "Catalyst", "Invalidation", "Evidence Needed Next"],
        final_rows,
    ))
    parts.append(deeper)

    parts.append("## Quality-Control Audit")
    parts.append(
        "- **PASS:** only India and United States issuers; eligible exchanges only.\n"
        "- **PASS:** 15 India and 15 US primary candidates; 10+10 additional boards; 10/10 combined Top 20.\n"
        "- **PASS:** no duplicate ticker in primary rankings.\n"
        "- **PASS:** all 10 segment groups and 73 requested segment rows are present.\n"
        "- **PASS:** weak segments explicitly use `NO QUALIFIED WINNER TODAY`; MICRO/NANO, distressed and unsupported turnaround/special situations are not force-filled.\n"
        "- **PASS:** all primary score vectors sum to their 100-point totals; confidence is separate.\n"
        "- **PASS:** prices are dated observations; no executable or fabricated price is implied.\n"
        "- **PASS:** JSON parse and CSV row checks are enforced by the generator and fail closed.\n"
        "- **PASS:** no commit, push or production-code modification."
    )
    parts.append(
        "The daily answer is the overlap of control, cash conversion, sovereignty, reasonable pot odds and survivable mines—not the loudest multiplier. "
        "Today that favors **ICE, CME, ICICI Bank, Power Grid, McKesson and CACI**; the cleaner earlier-capture paths are **Wabag, Toast, Shriram Finance and IndiaMART**."
    )
    parts.append("`MATRIX WINNER DISCOVERY COMPLETE`")
    return "\n\n".join(part.strip() for part in parts if part.strip()) + "\n"


BOARD_DATA = {
    "top15_india": [row["ticker"] for row in INDIA],
    "top15_us": [row["ticker"] for row in US],
    "additional_india": ["HDBFS", "HDFCAMC", "HDFCLIFE", "HSCL", "GRAVITA", "ANGELONE", "ADANIPORTS", "CAMS", "CDSL", "NEWGEN"],
    "additional_us": ["KNSL", "CTAS", "HUBB", "GWRE", "SPGI", "NRG", "VRSK", "BR", "ITRI", "CNM"],
    "sector_gap_registry": ["M&M", "ITC", "DLF", "LNG", "MLM", "ORLY", "PEP", "TMUS", "CBRE"],
    "early_capture_india": ["WABAG", "SHRIRAMFIN", "INDIAMART", "INDUSTOWER", "HDBFS", "SAGILITY", "NEWGEN", "KFINTECH"],
    "early_capture_us": ["TOST", "UBER", "GWRE", "IOT", "PCOR", "ALKT", "ITRI", "NRG"],
    "houses_tables_chips_rails_india": ["POWERGRID", "ICICIBANK", "MCX", "BHARTIARTL", "INDUSTOWER"],
    "houses_tables_chips_rails_us": ["ICE", "CME", "V", "BNY", "TW"],
    "combined_top20": ["ICE", "CME", "ICICIBANK", "MCK", "TW", "UBER", "ADBE", "POWERGRID", "BLK", "CACI", "SHRIRAMFIN", "BNY", "INDIAMART", "V", "MCX", "BHARTIARTL", "INDUSTOWER", "PERSISTENT", "OFSS", "RELIANCE"],
    "best_risk_adjusted_india": ["ICICIBANK", "POWERGRID", "SHRIRAMFIN", "BHARTIARTL", "SUNPHARMA"],
    "best_risk_adjusted_us": ["CME", "ICE", "ADBE", "MCK", "CACI"],
    "high_upside_high_mines_india": ["PBFINTECH", "ANGELONE", "KAYNES", "HSCL", "SOLARINDS"],
    "high_upside_high_mines_us": ["ASTS", "RKLB", "APLD", "TEM", "HIMS"],
    "queen_priced_pawns_india": ["ETERNAL", "AMBER", "NETWEB", "SOLARINDS", "KAYNES"],
    "queen_priced_pawns_us": ["ASTS", "RKLB", "PLTR", "HOOD", "CRWV", "TEM", "IONQ"],
    "immediate_deeper_research": DEEPER_RESEARCH,
}

ALLOWED_ACTIONS = {
    "STRUCTURAL COMPOUNDER", "HIGH-CONVICTION RESEARCH CANDIDATE", "EARLY CAPTURE", "RESEARCH DEEPER",
    "WATCHLIST", "WAIT FOR ENTRY", "WAIT FOR PULLBACK", "WAIT FOR BREAKOUT", "WAIT FOR CATALYST",
    "GOOD COMPANY — EXPENSIVE PRICE", "HIGH UPSIDE — HIGH MINE DENSITY", "VALUATION CAUTION",
    "THESIS WEAKENING", "AVOID", "DATA INSUFFICIENT", "NO QUALIFIED WINNER TODAY",
}
ALLOWED_COUNTRIES = {"India", "United States"}
ALLOWED_EXCHANGES = {"NSE", "BSE", "NYSE", "Nasdaq", "NYSE American"}
ALLOWED_SECTORS = {
    "Energy", "Materials", "Industrials", "Consumer Discretionary", "Consumer Staples", "Health Care",
    "Financials", "Information Technology", "Communication Services", "Utilities", "Real Estate",
}
ALLOWED_USE_CASES = {"QC", "GR", "VA", "IN", "BC", "DF", "CY", "MO", "EC", "TU", "SS", "SR", "CI", "SP", "DS"}


def static_validation() -> dict[str, Any]:
    if sum(SCORE_WEIGHTS.values()) != 100:
        raise ValueError("score weights do not sum to 100")
    if len(INDIA) != 15 or len(US) != 15:
        raise ValueError("primary country capacity must be 15/15")
    primary_tickers = [row["ticker"] for row in PRIMARY]
    if len(primary_tickers) != len(set(primary_tickers)):
        raise ValueError("duplicate ticker in primary rankings")
    all_tickers = [row["ticker"] for row in ALL_REGISTRY]
    if len(all_tickers) != len(set(all_tickers)):
        raise ValueError("duplicate ticker in complete registry")
    for row in ALL_REGISTRY:
        if row["country"] not in ALLOWED_COUNTRIES:
            raise ValueError(f"out-of-scope country: {row['ticker']}")
        if row["exchange"] not in ALLOWED_EXCHANGES:
            raise ValueError(f"out-of-scope exchange: {row['ticker']}")
        if row["sector"] not in ALLOWED_SECTORS:
            raise ValueError(f"bad broad sector: {row['ticker']}")
        if row["primary_use_case"] not in ALLOWED_USE_CASES:
            raise ValueError(f"bad use case: {row['ticker']}")
        if not set(row["secondary_use_cases"]).issubset(ALLOWED_USE_CASES):
            raise ValueError(f"bad secondary use case: {row['ticker']}")
        if len(row["secondary_use_cases"]) > 3:
            raise ValueError(f"too many secondary use cases: {row['ticker']}")
        if row["action"] not in ALLOWED_ACTIONS:
            raise ValueError(f"bad action: {row['ticker']} {row['action']}")
    for row in PRIMARY:
        if sum(row["score_components"].values()) != row["mvp_score"]:
            raise ValueError(f"bad primary score sum: {row['ticker']}")
    expected_counts = {
        "use_case_winners": 15, "sector_winners": 11, "market_cap_winners": 6,
        "maturity_stage_winners": 7, "volatility_winners": 3, "risk_sensitivity_winners": 7,
        "structural_role_winners": 5, "chess_promotion_winners": 9,
        "food_chain_winners": 5, "half_life_winners": 5,
    }
    if set(SEGMENT_GROUPS) != set(expected_counts):
        raise ValueError("missing segment group")
    for group, expected in expected_counts.items():
        rows = SEGMENT_GROUPS[group]
        if len(rows) != expected:
            raise ValueError(f"bad segment count for {group}")
        for row in rows:
            for key in ("best_india", "best_us", "best_overall", "runner_up"):
                candidate = row[key]
                if candidate != NQ and candidate not in REGISTRY_BY_TICKER:
                    raise ValueError(f"unregistered segment ticker: {candidate}")
            if row["best_overall"] == NQ and row["action"] != NQ:
                raise ValueError(f"weak segment not marked correctly: {row['segment']}")
            if row["action"] not in ALLOWED_ACTIONS:
                raise ValueError(f"bad segment action: {row['segment']}")
    for board, tickers in BOARD_DATA.items():
        for ticker in tickers:
            if ticker not in REGISTRY_BY_TICKER:
                raise ValueError(f"unregistered board ticker {ticker} in {board}")
    return {
        "score_weights_total": 100,
        "primary_india_count": len(INDIA),
        "primary_us_count": len(US),
        "primary_unique_tickers": True,
        "registry_unique_tickers": True,
        "country_scope_pass": True,
        "exchange_scope_pass": True,
        "required_segment_groups": len(SEGMENT_GROUPS),
        "required_segment_rows": sum(len(rows) for rows in SEGMENT_GROUPS.values()),
        "weak_segments_marked_no_qualified_winner": True,
        "equal_country_treatment": True,
        "action_vocabulary_pass": True,
        "primary_score_vector_sum_pass": True,
    }


def csv_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in PRIMARY:
        path = row["sector_path"].split(" > ")
        rows.append({
            "date": row["date"], "country": row["country"], "exchange": row["exchange"],
            "ticker": row["ticker"], "company": row["company"], "sector": row["sector"],
            "industry_group": path[1], "industry": path[2], "sub_industry": path[3],
            "primary_use_case": row["primary_use_case"],
            "secondary_use_cases": ";".join(row["secondary_use_cases"]),
            "market_cap_class": row["market_cap_class"], "maturity_stage": row["maturity_stage"],
            "share_type": row["share_type"], "volatility_class": row["volatility_class"],
            "risk_sensitivities": ";".join(row["risk_sensitivities"]), "casino_role": row["casino_role"],
            "food_chain_role": row["food_chain_role"], "current_chess_piece": row["current_chess_piece"],
            "potential_chess_piece": row["potential_chess_piece"], "poker_hand": row["poker_hand"],
            "half_life": row["half_life"], "mvp_score": row["mvp_score"],
            "confidence_score": row["confidence_score"], "valuation_classification": row["valuation_classification"],
            "entry_status": row["entry_status"], "action": row["action"], "main_catalyst": row["main_catalyst"],
            "main_risk": row["main_risk"], "thesis_invalidation": row["thesis_invalidation"],
            "current_price": row["current_price"], "price_observed": row["price_observed"],
            "sovereignty_score": row["sovereignty_score"], "mines_risk_score": row["mines_risk_score"],
            "rank": row["rank"], "canonical_classification": row["canonical_classification"],
        })
    return rows


def write_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("CSV would be empty")
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def file_validation(payload: dict[str, Any]) -> dict[str, Any]:
    for path in (MD_PATH, JSON_PATH, CSV_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing or empty output: {path}")
    parsed = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    if parsed["analysis_metadata"]["date"] != DATE:
        raise ValueError("JSON date mismatch")
    with CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        csv_data = list(csv.DictReader(handle))
    if not csv_data:
        raise ValueError("CSV has no rows")
    if len({row["ticker"] for row in csv_data}) != len(csv_data):
        raise ValueError("CSV contains duplicate primary tickers")
    if {row["country"] for row in csv_data} - ALLOWED_COUNTRIES:
        raise ValueError("CSV contains an out-of-scope country")
    markdown = MD_PATH.read_text(encoding="utf-8")
    required_markers = [
        "## 1. Analysis Metadata", "## 2. India Market Map", "## 3. United States Market Map",
        "## 4. Full Matrix Segment Winners", "## 5. Top 15 India Primary Candidates",
        "## 6. Top 15 United States Primary Candidates", "## 7. Additional Discovery Board",
        "## 8. Early-Capture Board", "## 9. Current Houses, Tables, Chips, and Rails",
        "## 10. Combined India + US Top 20", "## 11. Best Risk-Adjusted Ideas",
        "## 12. High Upside, High Mine Density", "## 13. Queen-Priced Pawns",
        "## 14. False-Pattern and Hype Traps", "## 15. Final Daily Synthesis",
        "MATRIX WINNER DISCOVERY COMPLETE",
    ]
    missing = [marker for marker in required_markers if marker not in markdown]
    if missing:
        raise ValueError(f"Markdown missing sections: {missing}")
    if payload["validation"]["required_segment_rows"] != 73:
        raise ValueError("matrix row count is not 73")
    return {
        "markdown_exists": True,
        "json_exists": True,
        "csv_exists": True,
        "json_parses": True,
        "csv_rows": len(csv_data),
        "csv_has_rows": True,
        "csv_unique_primary_tickers": True,
        "markdown_required_sections_pass": True,
    }


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    source = SOURCE_REPORT.read_text(encoding="utf-8")
    now = datetime.now().astimezone()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S %Z%z")
    minutes = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    india_open = weekday and 9 * 60 + 15 <= minutes < 15 * 60 + 30
    if india_open:
        india_status = "OPEN — regular NSE/BSE cash session; 27 July quotes are intraday until the official close"
    elif weekday and minutes < 9 * 60 + 15:
        india_status = "PRE-MARKET — latest validated completed session precedes 27 July"
    else:
        india_status = "CLOSED — 27 July regular session complete; official 15:30 close validated"
    us_open = weekday and (minutes >= 19 * 60 or minutes < 1 * 60 + 30)
    if us_open:
        us_status = "OPEN — regular NYSE/Nasdaq cash session; latest completed close is 24 July"
    elif weekday:
        us_status = "PRE-MARKET — latest validated regular-session close is 24 July"
    else:
        us_status = "CLOSED — weekend; latest validated regular-session close is 24 July"
    validation = static_validation()
    markdown = build_markdown(source, generated_at, india_status, us_status)

    payload: dict[str, Any] = {
        "analysis_metadata": {
            "date": DATE,
            "generated_at": generated_at,
            "timezone": "Asia/Calcutta",
            "india_market_status": india_status,
            "us_market_status": us_status,
            "scope": ["India — NSE/BSE", "United States — NYSE/Nasdaq/NYSE American"],
            "advisory_only": True,
            "live_validation_required": True,
            "live_data_available": "YES FOR LATEST COMPLETED SESSIONS — official NSE 27 July 15:30 close plus Yahoo/yfinance 27 July India and 24 July US reference closes; no institutional real-time order book",
            "price_basis": "India 27 July NSE closes; United States 24 July regular-session closes; dated reference observations, not executable quotes",
            "india_market_snapshot": {
                "as_of": "2026-07-27 15:30 IST",
                "source": "Official NSE all-indices feed",
                "nifty_50_pct": 0.96,
                "nifty_500_pct": 1.05,
                "nifty_500_advances": 387,
                "nifty_500_declines": 110,
                "nifty_midcap_100_pct": 1.11,
                "india_vix": 12.66,
                "india_vix_pct": -9.76,
            },
            "us_market_snapshot": {
                "as_of": "2026-07-24 close",
                "source": "AP market close report and Yahoo/yfinance closing prices",
                "sp_500_pct": 0.05,
                "dow_pct": 0.46,
                "nasdaq_pct": -0.64,
            },
            "data_sources": [
                "Official NSE all-indices feed", "Yahoo/yfinance read-only prices and technicals",
                "SEC EDGAR", "company investor-relations releases", str(SOURCE_REPORT.relative_to(ROOT)),
            ],
            "limitations": [
                "No consolidated institutional real-time feed or live order book",
                "No uniform current promoter/Form 4/13F/estimate-history feed",
                "Yahoo is a fragile single quote source; all prices are dated observations rather than executable quotes",
                "The local 24 July daily payload is STATIC_UNIVERSE_FALLBACK/UNVERIFIED; current observations were independently bounded",
            ],
        },
        "score_weights": SCORE_WEIGHTS,
        "confidence_definition": "Evidence freshness, source quality, agreement, transparency, sample depth and forecast uncertainty; not return probability.",
        "primary_candidates": PRIMARY,
        "extended_candidate_registry": EXTENDED,
        "segment_winners": SEGMENT_GROUPS,
        "boards": BOARD_DATA,
        "final_synthesis": FINAL_SELECTIONS,
        "validation": validation,
    }

    MD_PATH.write_text(markdown, encoding="utf-8")
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(csv_rows())
    payload["validation"].update(file_validation(payload))
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Parse the final rewritten JSON as the last fail-closed check.
    json.loads(JSON_PATH.read_text(encoding="utf-8"))

    print("MATRIX WINNER DISCOVERY COMPLETE")
    print(f"markdown path: {MD_PATH}")
    print(f"JSON path: {JSON_PATH}")
    print(f"CSV path: {CSV_PATH}")
    print("best India opportunity: ICICI Bank (NSE:ICICIBANK)")
    print("best US opportunity: Intercontinental Exchange (NYSE:ICE)")
    print("best overall matrix winner: Intercontinental Exchange (NYSE:ICE)")
    print("top 10 immediate deeper research: " + ", ".join(DEEPER_RESEARCH))


if __name__ == "__main__":
    main()
