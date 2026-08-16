# Sleeping Passenger — Daily India + United States Stock Discovery

## Analysis metadata

- **Analysis date:** Thursday, 16 July 2026
- **Analysis/data time:** 10:16 IST (04:46 UTC; 00:46 EDT), Asia/Calcutta
- **India market status:** **OPEN** in the regular 09:15–15:30 IST cash session.
- **United States market status:** **CLOSED**. The prices in this report are 15 July regular-session closes; the next NYSE/Nasdaq core session opens at 09:30 EDT / 19:00 IST.
- **Latest reporting periods used:** India Q4/FY2025-26 ended 31 March 2026, except fresh Q1 FY2026-27 results for HDFC Life, HDFC AMC, HDB Financial, Himadri, Angel One and Jana SFB. US calendar Q1 2026, with fresh Q2 2026 results for BlackRock and BNY, Adobe FQ2 FY26, Veeva FQ1 FY27, Copart FQ3 FY26, CACI FQ3 FY26, McKesson FY26 and Cintas FY26.
- **Price basis:** India prices are rounded read-only Yahoo/NSE observations at approximately 10:14–10:16 IST. US prices are 15 July closes. They are not executable bids or offers.
- **Freshness basis:** Compared with [15 July's complete screen](daily_stock_discovery_2026-07-15.md). A name appearing anywhere in that report is `RETAINED FROM PRIOR SCREEN`; otherwise it is `NEW DISCOVERY`.
- **Scope:** NSE/BSE and NYSE/Nasdaq/NYSE American only. Foreign ADRs and Cboe BZX-listed CBOE were excluded from primary eligibility.
- **Use:** Advisory research only. Scores are comparative research judgments, not return forecasts, guarantees or trade instructions.

### Important access limitations

There is no consolidated institutional real-time feed, live order book, complete estimate-history database, or uniformly refreshed promoter/insider/institutional transaction feed. Forward multiples are provider estimates unless explicitly tied to company guidance. Bank/NBFC/insurer free cash flow is not decision-useful; capital, funding, asset quality, solvency and ROE replace it. Current ownership, promoter encumbrance, related-party, Form 4 and securities-lending fields that were not freshly verified are marked: `LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT`.

Local pipeline artifacts were not treated as live evidence: the latest workspace market payload was a stale static fallback and the prior temporary quote scripts were absent. Quotes and technicals were therefore independently refreshed through bounded read-only provider calls; official filings control where provider fields conflict.

## Scoring and normalization

The requested 100-point weights are used exactly: Structural Node 10; Sovereignty 9; Promotion Geometry 11; Fundamentals 12; Cash/Balance Sheet 8; Valuation/Pot Odds 10; Catalysts 8; Entry 7; Poker EV 7; Mines Survival 7; Half-Life 5; Clairefontaine 4; Fallacy Protection 2.

Confidence is separate: 90–100 exceptional evidence; 75–89 strong; 60–74 moderate; 40–59 weak/incomplete; below 40 speculative. Confidence discounts missing live ownership/governance fields even where financial disclosure is strong.

India and the US were researched independently with equal candidate capacity. Combined ranks use **50% matched country/sector/size percentile, 25% own-history percentile and 25% absolute economic hurdle**. Banks are normalized on P/B, sustainable ROE, NIM, asset quality and capital; non-financials on through-cycle ROIC, FCF conversion, leverage and dilution. Combined rank therefore need not sort mechanically by raw score.

`Mines Risk /10` is a downside measure where 10 is worst. `MS /7` in the vectors is the positive survival score; it is not a mechanical inverse because runway, mine correlation and de-risking options matter.

### Auditable primary score vectors

Order: `SN/SV/PG/FQ/CB/VO/CI/EN/PE/MS/HL/CF/GF`.

| India ticker | Vector | Total |
|---|---|---:|
| ICICIBANK | 9/9/8/11/7/8/6/5/6/6/5/4/2 | 86 |
| HDFCBANK | 9/9/7/11/8/8/7/4/5/5/5/4/2 | 84 |
| POWERGRID | 10/9/5/11/5/8/7/5/6/5/5/4/2 | 82 |
| SHRIRAMFIN | 8/8/8/10/7/8/7/5/6/5/5/3/2 | 82 |
| INDIAMART | 8/8/10/9/8/9/6/5/6/5/4/3/1 | 82 |
| MCX | 10/9/8/11/8/4/7/3/6/4/5/4/2 | 81 |
| KFINTECH | 8/7/10/10/7/6/7/4/6/5/5/4/2 | 81 |
| BHARTIARTL | 9/8/7/11/6/5/7/5/6/5/5/4/2 | 80 |
| INDUSTOWER | 9/8/6/10/7/8/6/5/6/5/5/3/2 | 80 |
| PERSISTENT | 7/7/9/11/7/6/7/5/6/5/4/4/2 | 80 |
| OFSS | 8/8/8/10/8/6/6/3/6/5/5/4/2 | 79 |
| RELIANCE | 9/8/8/10/6/7/6/5/5/4/5/4/2 | 79 |
| LT | 8/8/7/11/6/6/8/4/5/4/5/4/2 | 78 |
| SUNPHARMA | 8/8/7/11/8/5/7/4/5/5/4/4/2 | 78 |
| WABAG | 7/6/10/10/7/6/7/4/5/4/5/4/2 | 77 |

| US ticker | Vector | Total |
|---|---|---:|
| ICE | 10/9/7/12/8/8/7/4/7/6/5/4/2 | 89 |
| CME | 10/9/6/12/8/8/7/4/7/6/5/4/2 | 88 |
| ADBE | 9/8/8/12/8/10/6/4/7/5/5/3/2 | 87 |
| UBER | 9/8/10/11/8/7/8/5/7/5/4/3/2 | 87 |
| MCK | 9/8/7/11/8/9/7/5/7/6/5/3/2 | 87 |
| TW | 9/8/8/11/8/7/8/5/7/5/5/4/2 | 87 |
| BLK | 9/8/8/12/7/8/8/3/7/5/5/4/2 | 86 |
| CACI | 8/8/9/11/7/9/8/5/7/5/4/3/2 | 86 |
| BNY | 10/9/7/12/7/7/8/2/6/6/5/4/2 | 85 |
| V | 10/9/5/12/8/6/6/5/7/6/5/4/2 | 85 |
| CPRT | 9/9/6/11/8/8/6/4/6/6/5/4/2 | 84 |
| TOST | 8/7/11/10/7/8/7/5/6/4/4/4/2 | 83 |
| VLTO | 8/9/5/12/7/7/6/5/6/6/5/4/2 | 82 |
| VEEV | 9/8/8/10/8/7/7/4/6/5/5/3/2 | 82 |
| MSA | 8/8/6/12/7/7/6/5/6/6/5/4/2 | 82 |

---

## SECTION 1 — TODAY'S MARKET ENVIRONMENT

### India

- **Market condition:** Headline green but internally narrow. At 10:05 IST Nifty 50 was **24,128.20 (+0.21%; 31 advances/19 declines)** and India VIX **12.94 (-2.52%)**. Nifty 500 was only +0.07% with **222 advances/271 declines**, while Midcap 100 was -0.17% and Smallcap 100 -0.20%. [Official NSE live indices](https://www.nseindia.com/api/allIndices)
- **Sector leadership:** IT was about +1.4% to +1.6%, auto roughly +0.7%, and consumer durables/oil-and-gas constructive. Bank Nifty was about -0.2% and broader financials and realty lagged. This is a selective evidence market, not broad risk-on confirmation.
- **Risk appetite and valuation:** Low VIX coexists with Midcap 100 around 30x and Smallcap 250 around 36x earnings. Small-cap theme exposure still has poor error tolerance even when breadth briefly improves.
- **Macro drivers:** June CPI was **4.38% YoY**, food CPI 5.32%, June WPI 9.87%, and the RBI repo rate 5.25%. Brent near $85 and US–Iran escalation raise INR, freight, aviation and working-capital mines. [Official CPI release](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2284125&lang=1&reg=1), [official WPI release](https://eaindustry.nic.in/press_release/press_release_202607.pdf), [RBI rate snapshot](https://m.rbi.org.in/scripts/publicationsview.aspx?id=19367)
- **Strongest opportunity areas:** Well-capitalized lenders; financial-market and registry rails; telecom towers/data; regulated transmission; banking workflow software; water infrastructure; selective digital engineering.
- **Areas to avoid/discount:** Leveraged renewables; oil-sensitive airlines; defence/rail/EMS/semiconductor names priced on order books without post-capex cash; weak-governance microcaps; internet-theme names at triple-digit implied durability.

### United States

- **Market condition:** Constructive but near-record and valuation-sensitive. On 15 July the S&P 500 rose **0.4% to 7,572.40**, Dow **0.3% to 52,658.64**, Nasdaq **0.6% to 26,269.23**, and Russell 2000 **0.4% to 2,976.26**. [AP market close](https://apnews.com/article/stock-markets-iran-inflation-oil-3544bd70e0f767404d2de91fd116d68e)
- **Sector leadership:** Financial infrastructure led on strong BNY/BlackRock results; recurring industrial services also held up. Healthcare lagged after managed-care claims concerns. AI/semiconductor price action remained volatile rather than uniformly strong.
- **Risk appetite and valuation:** The S&P was within 0.5% of its record. Investors rewarded converted earnings but the gap between profitable rails and pre-profit promotion stories widened.
- **Macro drivers:** June PPI fell 0.3% MoM but was still **5.5% YoY**; the 10-year yield eased to about 4.55%. Brent settled near **$84.95**. Retail sales, claims, the 28–29 July FOMC meeting and Q2 earnings are the dominant near-term variables. [Official BLS PPI](https://www.bls.gov/news.release/archives/ppi_07152026.htm)
- **Strongest opportunity areas:** Exchange/clearing/data rails; custody, settlement and collateral infrastructure; profitable software dislocations; healthcare throughput; mission systems; water/safety infrastructure; selected workflow promotion paths.
- **Areas to avoid/discount:** Pre-revenue space/quantum; leveraged AI clouds and data-centre construction; managed care without claims-cost proof; any “AI infrastructure” story that hides tenant, funding or dilution concentration.

### Price and entry check

- **India:** ICICI and Shriram were above both 50- and 200-day averages; Bharti, KFin and Persistent were above 50-day but below 200-day; MCX was below 50-day but above 200-day; Power Grid, IndiaMART, Reliance and L&T were below both. Sun and OFSS were at/near 52-week highs; WABAG was +74% over six months. This supports pullback/catalyst discipline, not momentum chasing.
- **US:** Visa, BNY and BlackRock were above both key averages, but BNY and BlackRock gapped 5.1% and 6.6% on results. ICE, CME, Tradeweb, CACI and Copart remained below both key averages, so their inclusion rests on made economics and pot odds. Toast, Veeva and Guidewire were recovery setups above 50-day but below 200-day.
- Volume/accumulation claims are intentionally omitted because there was no consolidated live order book and India intraday volume was incomplete.

---

## SECTION 2 — TOP 15 INDIA PRIMARY CANDIDATES

| Rank | Company | Ticker | Sector | Market Cap Category | Current Price | MVP Score /100 | Confidence /100 | Current Casino Role | Future Role | Current Chess Piece | Potential Piece | Poker Hand | Half-Life | Sovereignty /10 | Mines Risk /10 | Valuation | Entry Status | Main Catalyst | Main Risk | Action |
|---:|---|---|---|---|---:|---:|---:|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| 1 | ICICI Bank — RETAINED FROM PRIOR SCREEN | ICICIBANK | Private bank | Mega (≈₹10.2T) | ₹1,412.20 | 86 | 89 | House / Chip | Deeper House | Queen | Queen | Full House | Very Long | 9 | 3 | ATTRACTIVE | BUY-RESEARCH ZONE | Q1 deposits/NIM/asset quality | Deposit competition, NIM/slippage | STRUCTURAL COMPOUNDER |
| 2 | HDFC Bank — RETAINED FROM PRIOR SCREEN | HDFCBANK | Private bank | Mega (≈₹12.5T) | ₹812.05 | 84 | 88 | House / Chip | Deeper House | Queen | Queen | Full House | Very Long | 9 | 4 | ATTRACTIVE | WAIT FOR CATALYST | **CONFIRMED:** Q1 result 18 Jul | Merger drag, NIM and deposit mix | WAIT FOR CATALYST |
| 3 | Power Grid Corporation — RETAINED FROM PRIOR SCREEN | POWERGRID | Transmission utility | Large (≈₹2.62T) | ₹281.60 | 82 | 86 | House / Rail | Expanded Rail | Rook | Rook | Full House | Very Long | 9 | 4 | ATTRACTIVE | BUY-RESEARCH ZONE | Capitalization/renewable evacuation | Leverage and allowed-return change | STRUCTURAL COMPOUNDER |
| 4 | Shriram Finance — NEW DISCOVERY | SHRIRAMFIN | Diversified NBFC | Large (≈₹1.94T) | ₹1,030.60 | 82 | 88 | Player / Chip / Dealer | Credit-distribution House | Rook | Queen | Full House | Long | 8 | 4 | ATTRACTIVE | BUY-RESEARCH ZONE | Funding-cost and credit-cost normalization | Asset quality, funding and cycle | HIGH-CONVICTION RESEARCH CANDIDATE |
| 5 | IndiaMART InterMESH — RETAINED FROM PRIOR SCREEN | INDIAMART | B2B marketplace/SaaS | Mid (≈₹118B) | ₹1,961.40 | 82 | 84 | Table | SME Workflow House | Bishop | Queen | Straight | Long | 8 | 5 | ATTRACTIVE | WAIT FOR CATALYST | Paying-supplier/Busy stabilization | Supplier churn and weak conversion | WAIT FOR CATALYST |
| 6 | Multi Commodity Exchange — RETAINED FROM PRIOR SCREEN | MCX | Commodity exchange | Mid/Large (≈₹731B) | ₹2,865.60 | 81 | 84 | House / Table | Broader House | Rook | Queen | Straight Flush; overplayed | Very Long | 9 | 6 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | Q1 volume/RPC normalization | Rule shock, regulation, NSE entry | WAIT FOR CATALYST |
| 7 | KFin Technologies — RETAINED FROM PRIOR SCREEN | KFINTECH | Investor-service infrastructure | Mid (≈₹153B) | ₹885.20 | 81 | 84 | Dealer / Table | Global Asset-servicing Table | Bishop | Rook | Straight | Very Long | 7 | 5 | FAIRLY VALUED | WAIT FOR CATALYST | International organic growth/integration | Fee regulation and integration | EARLY CAPTURE |
| 8 | Bharti Airtel — RETAINED FROM PRIOR SCREEN | BHARTIARTL | Telecom/data infrastructure | Mega (≈₹11.6T) | ₹1,923.10 | 80 | 86 | Rail / Dealer | Table / House | Rook | Queen | Full House | Very Long | 8 | 5 | EXPENSIVE BUT DEFENSIBLE | BUY-RESEARCH ZONE | ARPU and capex moderation | Spectrum debt, regulation, Africa FX | STRUCTURAL COMPOUNDER |
| 9 | Indus Towers — NEW DISCOVERY | INDUSTOWER | Telecom towers | Large (≈₹1.08T) | ≈₹411 | 80 | 86 | Rail / Dealer | Telecom Infrastructure Table | Rook | Rook | Full House | Very Long | 8 | 5 | ATTRACTIVE | BUY-RESEARCH ZONE | Tenancy/5G loading and cash return | Customer concentration and regulation | STRUCTURAL COMPOUNDER |
| 10 | Persistent Systems — RETAINED FROM PRIOR SCREEN | PERSISTENT | Digital engineering | Mid/Large (≈₹806B) | ₹5,173.10 | 80 | 88 | Dealer | Workflow Table | Bishop | Rook | Full House | Long | 7 | 5 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | **CONFIRMED:** Q1 board/results 21–22 Jul | US spending, pricing and multiple | WAIT FOR CATALYST |
| 11 | Oracle Financial Services Software — NEW DISCOVERY | OFSS | Banking workflow software | Large (≈₹1.02T) | ₹11,752 | 79 | 88 | Dealer / Rail | Banking Workflow Table | Bishop | Rook | Full House | Very Long | 8 | 4 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | License/cloud conversion and product refresh | Oracle-parent dependence, low float, lumpiness | WAIT FOR PULLBACK |
| 12 | Reliance Industries — RETAINED FROM PRIOR SCREEN | RELIANCE | Digital/retail/energy platforms | Mega (≈₹17.7T) | ₹1,306.20 | 79 | 88 | Player / Table / House | Deeper House | Rook | Queen | Full House | Very Long | 8 | 5 | ATTRACTIVE | WAIT FOR CATALYST | **CONFIRMED:** Q1 result 17 Jul | Capex, O2C cycle and complexity | WAIT FOR CATALYST |
| 13 | Larsen & Toubro — RETAINED FROM PRIOR SCREEN | LT | Engineering/capital goods | Mega (≈₹5.18T) | ₹3,768.10 | 78 | 87 | Dealer / Rail | Infrastructure Table | Rook | Queen | Full House | Long | 8 | 5 | FAIRLY VALUED | BUY-RESEARCH ZONE | ₹7.40T order-book conversion | Mix, West Asia and working capital | HIGH-CONVICTION RESEARCH CANDIDATE |
| 14 | Sun Pharmaceutical — RETAINED FROM PRIOR SCREEN | SUNPHARMA | Pharmaceuticals | Large (≈₹4.67T) | ₹1,947.60 | 78 | 86 | Player / Dealer | Specialty Platform | Bishop | Rook | Full House | Long | 8 | 5 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | Innovative medicines/Organon integration | FDA, R&D and acquisition execution | WAIT FOR PULLBACK |
| 15 | VA Tech Wabag — NEW DISCOVERY | WABAG | Water treatment/EPC/O&M | Mid (≈₹128B) | ₹2,061.50 | 77 | 86 | Player / Dealer | Water Rail | Bishop | Rook | Straight | Long | 6 | 6 | FAIRLY VALUED | WAIT FOR PULLBACK | Framework conversion and O&M mix | EPC execution, receivables, country risk | EARLY CAPTURE |

### India candidate theses and invalidations

1. **ICICI Bank — WHY IT REMAINS:** FY26 PAT was ₹50,147 crore (+6.2%), loans +15.8%, deposits +11.4%, NIM 4.32%, GNPA 1.40%, NNPA 0.33% and CET1 16.35%. The made edge is capital plus underwriting plus payment/customer ownership; the market may underweight provisioning and fee resilience. Invalidate on NIM persistently below 4%, deposits materially lagging loans or renewed slippage. [Official FY26 filing](https://www.sec.gov/Archives/edgar/data/1103838/000095010326005960/dp245411_6k.htm)

2. **HDFC Bank — WHY IT REMAINS:** Q4 PAT was ₹19,221 crore (+9%), average deposits ₹28.51T (+12.8%), average advances ₹29.64T (+10%), NIM 3.38%, GNPA 1.15%, ROA 1.96% and CET1 17.3%. The market may extrapolate merger drag too far, but 18 July is a genuine validation point. Invalidate on renewed loan/deposit imbalance, NIM below 3.3% or stalled ROA normalization. [Official Q4 presentation](https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2025-2026/quarter-4/q4fy26-earnings-presentation.pdf), [board calendar](https://www.hdfc.bank.in/about-us/stakeholders-information/board-meet-intimation)

3. **Power Grid — WHY IT REMAINS:** FY26 sales were ₹46,733 crore and PAT ₹15,928 crore; capex ₹39,900 crore and capitalization ₹28,200 crore expand the regulated asset base. FCF is suppressed by expansion, but debt is paired with regulated assets and roughly 14x earnings is reasonable for a national renewable-evacuation rail. Invalidate on capitalization slippage, weaker allowed ROE or debt rising without commissioned assets. [Official financial-results archive](https://www.powergrid.in/en/financials), [company overview](https://www.powergrid.in/en/company-overview), [FY26 review](https://www.business-standard.com/markets/news/power-grid-s-long-term-prospects-remain-good-on-strong-order-visibility-126051901649_1.html)

4. **Shriram Finance — NEW DISCOVERY:** FY26 NII was ₹26,051.44 crore (+14.1%), PAT excluding the prior-year one-off was ₹9,998.15 crore (+20.9%), and AUM reached ₹302,273.75 crore (+14.9%). The market may underweight cross-product distribution and funding normalization, but this remains a credit-risk player rather than a pure house. Invalidate on rising Stage-3 assets/credit cost, liability-duration stress or growth bought through weaker underwriting. [Official FY26 release](https://cdn.shriramfinance.in/sfl-kalam/files/2026-04/SFL-Press-Release-Q4-FY2025-26.pdf)

5. **IndiaMART — WHY IT REMAINS:** FY26 revenue was ₹1,569 crore, EBITDA ₹530 crore, CFO ₹694 crore and conventional FCF about ₹687 crore, with cash/investments around ₹3,280 crore. Busy can promote discovery into SME workflow, but paying suppliers grew only 1% and declined sequentially. Invalidate after two more supplier-contraction quarters or collections growth below high single digits. [Official FY26 presentation](https://nsearchives.nseindia.com/corporate/INDIAMART_30042026162118_Investorpresentation.pdf), [cash-flow filing](https://nsearchives.nseindia.com/corporate/INDIAMART_30042026155322_Outcomeofmeeting.pdf)

6. **MCX — WHY IT REMAINS, WITH LOWER ENTRY SCORE:** FY26 total income was ₹2,429 crore, EBITDA ₹1,774 crore at roughly 73% and PAT ₹1,332 crore (+138%). Liquidity and price discovery are a genuine house, but a roughly 50x-plus multiple and rule-driven volume shock make the hand overplayed. Invalidate on sustained premium-turnover/RPC loss, regulatory damage or EBITDA margin below 60% without growth investment. [MCX investor relations](https://www.mcxindia.com/investor-relations), [July rule/volume risk](https://www.business-standard.com/markets/news/mcx-bse-shares-fall-up-to-5-5-extend-losses-to-4th-day-here-s-why-126070700549_1.html)

7. **KFin Technologies — WHY IT REMAINS:** FY26 operating revenue was ₹1,301.49 crore (+19.3%), EBITDA about ₹529.7 crore, core PAT roughly ₹353 crore, FCF about ₹271 crore and debt immaterial. International core revenue grew 26.2% organically; the missing value is exportable registry technology. Invalidate if organic international growth falls below 15%, EBITDA margin below 38% or retention weakens. [Official FY26 release](https://investor.kfintech.com/wp-content/uploads/2026/05/Intimation-Press-Release.pdf)

8. **Bharti Airtel — WHY IT REMAINS:** FY26 revenue was ₹210,973 crore (+22%), EBITDA ₹121,268 crore at 57.5%, with India ARPU ₹257; provider TTM FCF was about ₹50,896 crore. Capex normalization and enterprise/data optionality can deepen rail economics, but spectrum liabilities remain material. Invalidate on ARPU/ROIC stagnation, renewed capex intensity or adverse regulation. [Official FY26 release](https://assets.airtel.in/static-assets/cms/investor/docs/quarterly_results/2025-26/Q4/Press-Release.pdf)

9. **Indus Towers — NEW DISCOVERY:** FY26 revenue was ₹32,493.1 crore, EBITDA ₹17,975.6 crore at 55.3%, PAT ₹7,144.9 crore and conventional FCF ₹3,762.6 crore. It had ₹4,931.6 crore **net cash excluding lease liabilities**, but ₹15,274.4 crore **net debt including lease liabilities**; that distinction prevents overstating the balance-sheet floor. The filing reported 264,514 towers and 428,014 co-locations, while 31 March valuation was 15.44x P/E and 6.99x EV/EBITDA. Tower tenancy, co-location and 5G loading make it a toll rail rather than a handset/network-equipment bet. Invalidate on tenancy/collection deterioration, structurally higher capex, lease-adjusted leverage worsening or regulation weakening returns. [Official Q4/FY26 report](https://www.industowers.com/wp-content/uploads/2026/04/Quarterly-Report_Q4FY26-1.pdf)

10. **Persistent Systems — WHY IT REMAINS:** FY26 revenue rose 23.5% in INR to ₹14,748 crore, EBITDA was ₹2,706 crore, EBIT margin 15.6%, PAT ₹1,865 crore (+33.2%) and estimated FCF ₹1,351–1,572 crore with net cash. Growth is partly prepaid; 21–22 July tests deal conversion. Invalidate on constant-currency growth below 12%, EBIT below 15% or AI pricing compression. [Official FY26 presentation](https://www.persistent.com/wp-content/uploads/2026/04/analyst-presentation-and-factsheet-q4fy26.pdf), [board calendar](https://www.persistent.com/investors/investors-communication/tentative-bm-calendar/)

11. **OFSS — NEW DISCOVERY:** FY26 operating revenue was ₹7,672.1 crore, PAT ₹2,639.3 crore and diluted EPS ₹302.11; cash and bank balances were about ₹5,509.8 crore with no borrowings. Banking system-of-record software has long workflow half-life, but Oracle's roughly 72% parent stake, low float and lumpy licenses constrain sovereignty and entry. Invalidate on recurring/cloud mix stalling, license volatility without services conversion or minority-unfriendly capital allocation/RPTs. [Official FY26 filing](https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_152208_22042026210726_iXBRL_WEB.html)

12. **Reliance Industries — WHY IT REMAINS:** FY26 revenue was ₹11.76T (+9.8%), EBITDA ₹207,911 crore and net profit ₹95,754 crore (+17.8%); Jio revenue grew 14.6% and EBITDA 18.8%. Net debt was ₹124,717 crore and capex ₹144,271 crore. The market may underprice digital/retail mix shift, but complexity and new-energy execution remain mines. Invalidate on sustained negative FCF, leverage escalation or Jio/retail growth below high single digits. [Official financial review](https://www.ril.com/ar2025-26/financial-performance-and-review.html), [investor notices](https://www.ril.com/investors/shareholders-information)

13. **Larsen & Toubro — WHY IT REMAINS:** FY26 revenue was ₹285,874 crore (+12%), EBITDA ₹29,151 crore at 10.2%, recurring PAT ₹17,238 crore (+18%) and consolidated PAT ₹16,084 crore (+7%); the order book reached ₹740,327 crore (+28%) and net working capital/revenue improved to 4.1%. Backlog is evidence only if it converts to margin and cash. Consolidated FCF and net debt are not decision-useful without separating L&T Finance; for the non-financial cash/debt bridge: `LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT`. Invalidate on order-quality deterioration, project/manufacturing margin below 9%, working-capital reversal or weak cash conversion in the non-financial businesses. [Official FY26 financial results](https://2025prodstorageaccount-eqdyc8g8hpccdfez.a02.azurefd.net/ltprod/media/dryh21pu/2026-05-05-financial-results-for-the-year-ended-march-31-2026.pdf), [earnings transcript](https://investors.larsentoubro.com/upload/Analysttrans/FY2026AnalysttransL%26T%20Q4%20FY26%20Earnings%20Call%20Transcript.pdf)

14. **Sun Pharma — WHY IT REMAINS:** FY26 sales rose 11.9% to ₹58,220 crore, EBITDA **rose 16.1%** to ₹17,731 crore at 30.3%, PAT was ₹11,479 crore and debt/equity only 0.06. Innovative Medicines grew 16.4% and reached 20.7% of sales. Invalidate on FDA action, innovative-medicine deceleration or Organon integration/ROIC failure. [Official FY26 release](https://sunpharma.com/wp-content/uploads/2026/05/Press-Release-Sun-Pharma-Q4FY26-Financial-Result.pdf), [annual report](https://sunpharma.com/wp-content/uploads/2026/07/Sun-Pharma_AR-2025-26.pdf)

15. **VA Tech Wabag — NEW DISCOVERY:** FY26 operating revenue was ₹3,944.2 crore, total income ₹4,038.5 crore, EBITDA ₹524.1 crore (+22%) at 13.3%, PAT ₹370.5 crore (+26%) and conventional FCF approximately ₹201.5 crore; net cash was ₹833.7 crore. The order book exceeded ₹17,200 crore including frameworks, and the audit opinion was unmodified. The market may not fully credit the shift toward recurring O&M and scarce water capability, but frameworks are not firm cash until converted. Invalidate on receivables/working capital re-expanding, overseas execution losses or framework conversion failing. [Official FY26 result](https://www.wabag.com/wp-content/uploads/2026/05/SI_Q4FY2025-26_Results.pdf)

### India governance, ownership and liquidity gate

- ICICI and HDFC have no promoter; capital, underwriting, conduct and related-party controls replace pledge analysis.
- Power Grid is government controlled; policy dependence and minority-holder capital allocation are explicitly scored.
- Shriram, Bharti, Indus, Reliance, Sun, OFSS and Wabag require a same-day promoter/encumbrance, related-party, auditor and FII/DII refresh before execution. Oracle-parent control and OFSS low float receive an explicit discount.
- IndiaMART's March promoter holding was 49.12% with zero pledge. Current KFin strategic ownership, MCX institutional ownership and Persistent employee-equity issuance still require refresh.
- No primary passed solely on a theme, order book or price trend. Where current pledge/RPT/auditor/free-float data were not freshly verified: `LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT`.

---

## SECTION 3 — TOP 15 UNITED STATES PRIMARY CANDIDATES

| Rank | Company | Ticker | Sector | Market Cap Category | Current Price | MVP Score /100 | Confidence /100 | Current Casino Role | Future Role | Current Chess Piece | Potential Piece | Poker Hand | Half-Life | Sovereignty /10 | Mines Risk /10 | Valuation | Entry Status | Main Catalyst | Main Risk | Action |
|---:|---|---|---|---|---:|---:|---:|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| 1 | Intercontinental Exchange — RETAINED FROM PRIOR SCREEN | ICE | Exchanges/data/mortgage rails | Large ($79.08B) | $139.84 | 89 | 90 | House / Table | Deeper House | Queen | Queen | Straight Flush | Very Long | 9 | 4 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** Q2 30 Jul | Debt, mortgage cycle, regulation | STRUCTURAL COMPOUNDER |
| 2 | CME Group — RETAINED FROM PRIOR SCREEN | CME | Futures/clearing/data | Large ($88.59B) | $245.18 | 88 | 91 | House / Rail | Deeper House | Queen | Queen | Straight Flush | Very Long | 9 | 3 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** Q2 22 Jul | ADV/capture normalization | STRUCTURAL COMPOUNDER |
| 3 | Adobe — RETAINED FROM PRIOR SCREEN | ADBE | Creative/document software | Large ($89.26B) | $224.56 | 87 | 89 | Table / Dealer | Workflow House | Rook | Queen | Full House | Long | 8 | 5 | UNDERVALUED | WAIT FOR CATALYST | AI-first ARR conversion | AI displacement and interim CFO | WAIT FOR CATALYST |
| 4 | Tradeweb Markets — RETAINED FROM PRIOR SCREEN | TW | Electronic fixed-income trading | Large ($21.95B) | $100.68 | 87 | 90 | Dealer / Table | Multi-asset House | Rook | Queen | Full House | Very Long | 8 | 4 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** Q2 30 Jul | Share/capture-rate pressure | STRUCTURAL COMPOUNDER |
| 5 | Uber Technologies — RETAINED FROM PRIOR SCREEN | UBER | Mobility/delivery marketplace | Large ($147.93B) | $72.67 | 87 | 90 | Table | House | Rook | Queen | Full House | Long | 8 | 5 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** Q2 5 Aug; AV/FCF | Regulation, insurance and AV bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 6 | McKesson — RETAINED FROM PRIOR SCREEN | MCK | Healthcare distribution/services | Large ($93.23B) | $796.35 | 87 | 91 | Dealer / Rail | Oncology/Biopharma Table | Rook | Queen | Full House | Very Long | 8 | 5 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** FY27 Q1 5 Aug | CVS/channel concentration and policy | STRUCTURAL COMPOUNDER |
| 7 | BlackRock — NEW DISCOVERY | BLK | Asset/capital/technology platform | Large ($177.79B) | $1,093.40 | 86 | 94 | Table / Capital Rail | Capital/Data House | Rook | Queen | Full House | Very Long | 8 | 5 | ATTRACTIVE | WAIT FOR PULLBACK | HPS/private markets and Aladdin ACV | Market beta, integration and dilution | WAIT FOR PULLBACK |
| 8 | CACI International — RETAINED FROM PRIOR SCREEN | CACI | Mission technology | Mid ($10.42B) | $471.83 | 86 | 89 | Dealer / Rail | Mission Table | Bishop | Rook | Full House | Long | 8 | 4 | UNDERVALUED | BUY-RESEARCH ZONE | **CONFIRMED:** FY26/FY27 guide 5 Aug | Federal timing and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |
| 9 | BNY — NEW DISCOVERY | BNY | Custody/settlement/collateral | Large ($111.43B) | $162.35 | 85 | 95 | House / Rail | Deeper Capital House | Queen | Queen | Straight Flush | Very Long | 9 | 3 | FAIRLY VALUED | WAIT FOR PULLBACK | Platform leverage and collateral | Rate normalization and fee regulation | STRUCTURAL COMPOUNDER |
| 10 | Visa — RETAINED FROM PRIOR SCREEN | V | Payments/settlement | Mega ($675.39B) | $355.14 | 85 | 92 | House / Chip / Rail | Deeper House | Queen | Queen | Straight Flush | Very Long | 9 | 4 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | **CONFIRMED:** fiscal Q3 28 Jul | Regulation, litigation and new rails | WAIT FOR PULLBACK |
| 11 | Copart — RETAINED FROM PRIOR SCREEN | CPRT | Salvage-auction marketplace | Large ($25.26B) | $27.28 | 84 | 88 | Table / House | Deeper House | Rook | Queen | Full House | Very Long | 9 | 4 | ATTRACTIVE | WAIT FOR CATALYST | Unit/pricing stabilization | Insurer volumes and land returns | WAIT FOR CATALYST |
| 12 | Toast — RETAINED FROM PRIOR SCREEN | TOST | Restaurant/retail software-payments | Mid ($17.63B) | $30.39 | 83 | 87 | Dealer / Chip | Commerce Table | Bishop | Queen | Straight | Long | 7 | 5 | ATTRACTIVE | BUY-RESEARCH ZONE | Retail/international/non-payment attach | Restaurant cycle and SBC/dilution | EARLY CAPTURE |
| 13 | Veralto — RETAINED FROM PRIOR SCREEN | VLTO | Water/product-quality instruments | Large ($22.35B) | $91.00 | 82 | 88 | Dealer / Rail | Deeper Rail | Rook | Rook | Full House | Long | 9 | 3 | ATTRACTIVE | BUY-RESEARCH ZONE | **CONFIRMED:** Q2 call 29 Jul | Organic softness, tariffs and M&A | STRUCTURAL COMPOUNDER |
| 14 | Veeva Systems — RETAINED FROM PRIOR SCREEN | VEEV | Life-sciences cloud/data | Large ($31.46B) | $193.67 | 82 | 90 | Dealer / Table | Workflow House | Rook | Queen | Full House | Long | 8 | 4 | ATTRACTIVE | WAIT FOR CATALYST | Vault CRM/Data Cloud/AI agents | Transition, pharma budgets and SBC | WAIT FOR CATALYST |
| 15 | MSA Safety — RETAINED FROM PRIOR SCREEN | MSA | Safety equipment/standards | Mid ($6.52B) | $169.00 | 82 | 88 | Dealer / Rail | Safety Table | Bishop | Rook | Full House | Long | 8 | 3 | ATTRACTIVE | BUY-RESEARCH ZONE | Autronica integration/margin | Industrial cycle, tariffs and M&A | STRUCTURAL COMPOUNDER |

### United States candidate theses and invalidations

1. **ICE — WHY IT REMAINS:** Q1 net revenue rose 20% to $3.0B, operating margin was 56%, adjusted margin 65% and Q1 FCF about $1.15B. Clearing, energy/rates markets, fixed-income data and mortgage workflow are independent made edges. Invalidate on data slowdown, exchange share/capture loss or failed deleveraging. [Official Q1](https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-Reports-Record-First-Quarter-2026/default.aspx)

2. **CME — WHY IT REMAINS:** Q1 revenue rose 14% to $1.9B with a 72.8% adjusted operating margin and $3.36 adjusted EPS. Operating cash flow was $1,259.9M and capex $21.8M, implying conventional FCF near $1,238.1M; cash including FICC was $2.6B versus $3.4B debt. Proprietary liquidity, margin offsets and clearing earn regardless of market direction. Invalidate on persistent ADV/share loss, capture deterioration or adverse rule changes. [Official Q1](https://www.cmegroup.com/media-room/press-releases/2026/4/22/cme_group_inc_reportsrecordrevenueadjustedoperatingincomeadjuste.html)

3. **Adobe — WHY IT REMAINS, WITH A GOVERNANCE DISCOUNT:** FQ2 revenue was $6.62B (+13%), operating cash flow $2.17B and AI-first ARR exceeded $500M. At $224.56, official FY26 guidance implies about **12.5x GAAP EPS** or **9.2x non-GAAP EPS**, not the lower unlabeled provider multiple sometimes shown. The market prices severe disruption, but CFO Dan Durn's departure and interim-CFO transition are real mines. Invalidate on ARR deceleration, margin damage or AI products failing to preserve retention/pricing. [Official FQ2 release and guidance](https://www.adobe.com/cc-shared/assets/investor-relations/pdfs/11606202/a5543arefgt.pdf)

4. **Tradeweb — WHY IT REMAINS:** Q1 revenue rose 21.2%, ADV 31.4%, adjusted EBITDA margin reached 55%, and TTM FCF was approximately $1.10B. Cash of $1.94B and an undrawn revolver protect multi-asset expansion. Invalidate on sustained cash-credit share/fee loss or organic growth below low double digits. [Official Q1](https://investors.tradeweb.com/static-files/92e4d1e6-ba56-42ae-9c42-1c76b6a8bb70)

5. **Uber — WHY IT REMAINS:** Q1 revenue rose 14%, bookings 25%, adjusted EBITDA 33% and FCF reached $2.3B. Memberships, ads and AV distribution can deepen table economics without owning every vehicle. Invalidate if bookings fall below mid-teens, insurance/regulation destroys leverage or AV partners bypass the network. [Official Q1](https://investor.uber.com/news-events/news/press-release-details/2026/Uber-Announces-Results-for-First-Quarter-2026/default.aspx)

6. **McKesson — WHY IT REMAINS:** FY26 revenue rose 12% to $403.4B and FCF reached $5.4B; oncology and biopharma services can expand the margin pool beyond wholesaling. The discount is deserved: CVS was 24% of revenue, the top ten customers 73%, and opioid liabilities/negative equity matter. Invalidate on major-customer loss, policy damage or services failing to outgrow distribution. [FY26 release](https://www.sec.gov/Archives/edgar/data/927653/000092765326000066/mck_exhibit991x3312026.htm), [Form 10-K](https://www.sec.gov/Archives/edgar/data/927653/000092765326000069/mck-20260331.htm)

7. **BlackRock — NEW DISCOVERY:** Q2 revenue rose 31% to $7.084B, adjusted EPS **rose 15%**, AUM reached $15.3T and Q2 net inflows were $192B. Aladdin technology/subscription revenue rose 13%, strengthening the table-to-data-house path. The 6.6% result-day gap weakens entry, and diluted shares rose about 5% largely through HPS transaction units. Invalidate on organic base-fee collapse, Aladdin ACV slowing, HPS integration failure or dilution overwhelming EPS. [Official Q2](https://www.blackrock.com/corporate/newsroom/press-releases/article/corporate-one/press-releases/blackrock-reports-second-quarter-2026)

8. **CACI — WHY IT REMAINS:** Fiscal Q3 revenue grew 8.5%, EBITDA 14.3%, FCF 17.8% and backlog reached $33.4B. Mission/cyber/signals mix is growing faster than labor services at about 15x provider-forward earnings. Invalidate on backlog/book-to-bill deterioration, ARKA leverage remaining high or FCF/share failing to compound. [Official Q3](https://investor.caci.com/2026-04-22-CACI-Reports-Results-for-Its-Fiscal-2026-Third-Quarter), [5 August date](https://investor.caci.com/2026-07-09-CACI-Schedules-Conference-Call-to-Discuss-Fourth-Quarter-and-Full-Fiscal-Year-2026-Results%2C-and-to-Provide-Fiscal-Year-2027-Guidance)

9. **BNY — NEW DISCOVERY:** Q2 revenue rose 13% to $5.698B, EPS 27% to $2.45, pre-tax margin reached 39.8% and ROTCE 31.3%. AUC/A rose 12% to $62.6T; clearance/collateral revenue rose 16% and payments/trade 17%; CET1 was 11%. The market may still treat BNY as a rate-sensitive custodian rather than a settlement/collateral house, but the 5.1% gap to a high and roughly 5x tangible book argue for patience. Invalidate on fee slowdown, falling platform margins, capital pressure or NII reversal without fee offset. [Official Q2](https://www.bny.com/content/dam/bnymellon/documents/pdf/investor-relations/earnings/earnings-press-release-2q-2026.pdf)

10. **Visa — WHY IT REMAINS:** Fiscal Q2 revenue rose 17%, net income 32% and GAAP operating margin was 64.4%; six-month OCF was $9.79B. The payment chip is exceptional, but roughly 31x trailing earnings and a price near the yearly high weaken pot odds. Invalidate on take-rate regulation, cross-border deceleration or material new-rail disintermediation. [Official Q2](https://www.sec.gov/Archives/edgar/data/1403161/000140316126000077/q22026earningsrelease.htm)

11. **Copart — WHY IT REMAINS:** Fiscal Q3 revenue rose only 2.1% but gross profit 3.7%; provider TTM FCF is about $1B and cash around $4.2B against negligible debt. Yard density, insurer integration, title/logistics and global buyer liquidity persist through the slowdown. Invalidate if units remain weak without price/share gains or land investment ceases to earn attractive returns. [Official Q3](https://www.copart.com/content/us/en/press-releases/copart-reports-third-quarter-2026-results)

12. **Toast — WHY IT REMAINS:** Q1 ARR grew 26% to $2.2B, locations 22%, GPV 22% and FCF reached $115M. Retail, international, payroll and capital can promote POS/payments into a commerce table. Invalidate on location/GPV growth below mid-teens, take-rate pressure or SBC preventing per-share conversion. [Official Q1](https://investors.toasttab.com/financials/quarterly-results/default.aspx)

13. **Veralto — WHY IT REMAINS:** Q1 sales rose 6.7%, operating margin was 23.8%, FCF $170M and roughly 60% of sales are recurring. Water and regulated measurement create installed-base/consumable half-life. Invalidate if core growth remains below 2%, recurring mix weakens or post-M&A leverage rises. [Official Q1](https://www.sec.gov/Archives/edgar/data/1967680/000196768026000023/vlto-20260428xex991.htm)

14. **Veeva — WHY IT REMAINS:** Fiscal Q1 revenue rose 16%, subscription revenue 15%, operating margin was 30.9%, and liquidity was $7.313B with no funded debt. Vault CRM, Data Cloud and AI agents improve technology independence. Invalidate on subscription growth below low double digits, migration delays or SBC/per-share FCF deterioration. [Official fiscal Q1](https://ir.veeva.com/financials/quarterly-results/default.aspx?languageid=1)

15. **MSA Safety — WHY IT REMAINS:** Q1 sales were $463.6M (+10% GAAP, +3% organic), operating income $93.0M at 20.1%, net income $71.3M and FCF $65.1M (91% conversion). Cash was $180.2M against $613.1M current and long-term debt, or $433M net debt and 0.9x net leverage, with $1.2B liquidity. At $169 the quote is roughly 27.7x provider TTM FCF—reasonable only if standards economics and Autronica integration sustain growth. Invalidate on organic contraction, margin below 18% or acquisition leverage/returns disappointing. [Official Q1 release](https://investors.msasafety.com/news-releases/news-release-details/msa-safety-announces-first-quarter-2026-results)

### United States ownership, dilution and concentration gate

- Adobe, Uber, Toast and Veeva require diluted FCF/share and SBC monitoring; adjusted EBITDA alone does not clear the gate.
- ICE, CME, Tradeweb, BNY and Visa face direct regulation, data/capture-rate scrutiny and operational/cyber concentration. House economics do not remove rule risk.
- BlackRock's HPS units raised diluted shares; private-market integration and per-share earnings conversion are explicit gates. McKesson's CVS/top-ten customer concentration and CACI's federal-customer/acquisition leverage are explicit.
- Current Form 4 activity, full institutional-ownership changes and securities-lending concentration were not uniformly refreshed: `LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT`.

### Primary-candidate cross-framework audit

This table completes the economic-food-chain, Clairefontaine, inflection and franchise-momentum tests. Promotion probability is conditional business-role migration—not a return forecast.

| Candidate | Food-chain node / who pays repeatedly | Clairefontaine | Inflection | Inherited floor → independent ceiling | Promotion probability / main capture mine |
|---|---|---:|---|---|---|
| ICICI Bank | Quaternary capital/payment permission; borrowers and depositors | 7 | REAL | Deposit franchise → independent fee/underwriting scale | 75% deeper House / funding and credit cycle |
| HDFC Bank | Quaternary capital/payment permission | 7 | EMERGING | HDFC brand/distribution → post-merger ROA ceiling | 70% deeper House / NIM normalization |
| Power Grid | Tertiary/quaternary regulated transmission | 7 | REAL | State mandate → commissioned renewable-evacuation base | 80% expanded Rail / regulation and leverage |
| Shriram Finance | Secondary/tertiary credit distribution | 6 | REAL | Legacy vehicle franchise → diversified customer wallet | 60% Dealer/Table / asset quality |
| IndiaMART | Tertiary discovery/aggregation | 5 | EMERGING | Supplier marketplace → Busy/workflow/payment ceiling | 60% House / supplier stagnation |
| MCX | Quaternary rules, matching, clearing and data | 7 | EMERGING | Incumbent liquidity → broader product/data control | 55% broader House / rule and competition |
| KFin | Tertiary registry/workflow infrastructure | 6 | REAL | Domestic installed base → global servicing platform | 70% Table / integration and fee caps |
| Bharti Airtel | Tertiary network/distribution/payment proximity | 7 | REAL | Spectrum/brand → enterprise/data/payment ceiling | 65% Table/House / debt and regulation |
| Indus Towers | Tertiary passive network infrastructure | 6 | REAL | Anchor tenants → multi-tenant/overseas rail ceiling | 60% Table / tenant concentration |
| Persistent | Secondary services → tertiary workflow | 6 | REAL | Client relationships → reusable IP/workflow ceiling | 55% Rook/Table / pricing and concentration |
| OFSS | Tertiary core-banking workflow | 6 | EMERGING | Oracle distribution → independent cloud/product ceiling | 55% Table / parent, low float, lumpiness |
| Reliance | Producer plus tertiary distribution/platforms | 7 | REAL | Capital/brand → Jio/retail/new-energy ceiling | 65% deeper House / capex and complexity |
| L&T | Secondary project execution → infrastructure access | 7 | REAL | National engineering franchise → digital/asset-light table | 55% Table / mix and working capital |
| Sun Pharma | Producer plus specialty distribution | 7 | REAL | India generics floor → innovative-medicine ceiling | 55% Rook / R&D, FDA and M&A |
| Wabag | Producer/dealer → critical water workflow | 5 | EMERGING | EPC references → recurring O&M/technology rail | 60% Rook / receivables and sovereign execution |
| ICE | Quaternary matching, clearing, data and workflow | 7 | REAL | Exchange liquidity → multi-rail data/workflow ceiling | 80% deeper House / regulation and debt |
| CME | Quaternary benchmarks, clearing and collateral | 7 | REAL | Member liquidity → product/data/collateral depth | 80% deeper House / ADV and capture |
| Adobe | Tertiary creative/document workflow | 7 | EMERGING | Installed creators → AI/document transaction ceiling | 60% House / AI displacement and governance |
| Tradeweb | Tertiary electronic market table | 7 | REAL | Dealer/client network → multi-asset protocol control | 70% House / share and capture |
| Uber | Tertiary local-market aggregation | 6 | REAL | Mobility liquidity → ads/membership/AV distribution | 65% House / regulation and AV bypass |
| McKesson | Tertiary healthcare distribution/workflow | 7 | REAL | Distribution scale → oncology/biopharma services | 65% Table / customer and policy concentration |
| BlackRock | Tertiary/quaternary capital aggregation/data | 7 | REAL | AUM/ETF floor → Aladdin/private-markets ceiling | 65% Data House / market beta, integration, dilution |
| CACI | Secondary mission service → embedded infrastructure | 6 | REAL | Federal access → differentiated cyber/signals systems | 60% Rook/Table / award timing and leverage |
| BNY | Quaternary custody, settlement, collateral, payments | 7 | REAL | 240-year trust floor → platform operating model ceiling | 75% deeper House / fee/rate/cyber risk |
| Visa | Quaternary payment permission/settlement | 8 | REAL | Global acceptance → value-added/real-time services | 80% deeper House / regulation and new rails |
| Copart | Tertiary marketplace/logistics/title | 7 | EMERGING | Yard/buyer density → deeper global service control | 65% deeper House / volume and land returns |
| Toast | Secondary dealer/chip → tertiary commerce table | 6 | REAL | Restaurant POS floor → retail/payroll/capital ceiling | 70% Table / cycle and SBC |
| Veralto | Tertiary measurement/compliance infrastructure | 7 | REAL | Installed instruments → consumables/data ceiling | 70% deeper Rail / organic softness and M&A |
| Veeva | Tertiary regulated life-science workflow/data | 7 | REAL | Pharma installed base → independent Data Cloud/CRM | 65% House / transition and SBC |
| MSA Safety | Tertiary certified safety standard/installed base | 7 | REAL | Certification/replacement floor → connected safety table | 55% Rook/Table / cycle and integration |

No primary thesis is classified as a narrative-only inflection. The weakest conversion points—IndiaMART supplier growth, MCX post-rule volume, OFSS cloud mix, Wabag framework conversion, Adobe AI retention and Copart unit growth—remain explicitly conditional.

---

## SECTION 4 — INDIA ADDITIONAL DISCOVERY BOARD

Exactly ten names passed the secondary screen. Six are fresh mid/small-cap or earlier-stage discoveries; the board therefore meets the under-followed-capacity requirement without lowering the evidence gate.

| Company | Ticker | Score /100 | Confidence /100 | Category | Main reason to research | Primary risk |
|---|---|---:|---:|---|---|---|
| HDB Financial Services — **NEW DISCOVERY** | HDBFS | 77 | 87 | Mid-cap lending Dealer | Q1 FY27 PAT ₹785 crore, +38.3% YoY; NII +19.9%, AUM about ₹1.22 trillion and NIM 8.35% support a broader underserved-borrower franchise | Unsecured/SME credit costs, parent-channel dependence and recent-listing price discovery |
| HDFC Asset Management — **NEW DISCOVERY** | HDFCAMC | 77 | 90 | Savings Table | Q1 PAT about ₹838 crore, +12%; quarterly average AUM about ₹9.35 trillion, +13%, gives direct participation in Indian financialization | Fee caps, passive-mix pressure and roughly 38x trailing earnings |
| HDFC Life — **NEW DISCOVERY** | HDFCLIFE | 76 | 89 | Insurance Chip/Risk Rail | Q1 new-business premium +12%, APE +9% and VNB +8.7% to ₹879 crore show converted distribution rather than only a penetration narrative | VNB margin stalled near 25%, persistency softened and regulation can reset economics |
| Himadri Speciality Chemical — **NEW DISCOVERY** | HSCL | 75 | 84 | Critical-materials Bishop | Q1 revenue rose 28% to ₹1,432 crore and PAT about 27% to ₹228 crore as specialty/new-energy materials scaled | Capex, technology qualification, commodity inputs and cash conversion; entry is extended near its 52-week high |
| Gravita India — **NEW DISCOVERY** | GRAVITA | 74 | 84 | Recycling Bishop → Rook | Multi-country recycled-lead/aluminium/plastics loop, roughly 21% FY26 PAT growth and about 24% indicated ROIC merit a circular-material rail test | Metal prices, environmental compliance, working capital and overseas execution |
| Angel One — **NEW DISCOVERY** | ANGELONE | 73 | 86 | Broker Dealer → Financial Table | Q1 income +25.4% and PAT +102% YoY, plus wealth/AMC/client-funding options, create non-broking promotion paths | PAT fell 27.8% QoQ, EBITDA margin fell to 33.9%, while trading rules and client-credit losses remain correlated mines |
| Adani Ports — **RETAINED FROM PRIOR SCREEN** | ADANIPORTS | 77 | 83 | Logistics Table → House | **WHY IT REMAINS:** port density, rail/logistics links and international assets can deepen end-to-end cargo control | Group-governance discount, leverage, geopolitics and return discipline outside India |
| CAMS — **RETAINED FROM PRIOR SCREEN** | CAMS | 72 | 84 | Asset-servicing Rail | **WHY IT REMAINS:** recurring registrar workflow and cash conversion remain strong as mutual-fund penetration rises | AMC concentration, pricing regulation and competing technology rails |
| CDSL — **RETAINED FROM PRIOR SCREEN** | CDSL | 71 | 83 | Depository House/Rail | **WHY IT REMAINS:** dematerialized-account and settlement participation is a long-half-life capital-market toll | Transaction cyclicality, tariff regulation, cybersecurity and premium valuation |
| Newgen Software — **RETAINED FROM PRIOR SCREEN** | NEWGEN | 70 | 80 | Workflow Pawn → Rook | **WHY IT REMAINS:** content/process automation can become embedded regulated-enterprise infrastructure if recurring/cloud mix rises | Large-deal lumpiness, receivables, global platform competition and incomplete FCF proof |

Evidence anchors: [HDFC AMC financial-information page](https://www.hdfcfund.com/about-us/financial-information/financial-results) and [current Q1 report](https://economictimes.indiatimes.com/markets/stocks/news/hdfc-amc-q1-results-net-profit-rises-12-to-rs-837-crore-revenue-up-14/articleshow/132413400.cms), [HDFC Life investor relations](https://www.hdfclife.com/about-us/investor-relations) and [current Q1 report](https://www.livemint.com/market/stock-market-news/hdfc-life-insurance-company-q1-results-profit-rises-12-yoy-to-611-crore-vnb-up-9-11784114501728.html), [HDB official investor archive](https://www.hdbfs.com/investors) and [current Q1 reporting](https://www.financialexpress.com/business/banking-finance-hdb-financial-q1fy27-profit-up-38-net-interest-margin-edges-higher-at-8-35-4292412/lite/), [Himadri official financial-information portal](https://www.himadri.com/home/) and [current Q1 reporting](https://www.business-standard.com/amp/companies/quarterly-results/himadri-q1-boosts-rs-240-cr-capex-for-advanced-materials-expansion-126071501411_1.html), [Gravita financials](https://www.gravitaindia.com/investors/financial-details), and [Angel One filings page](https://www.angelone.in/investor-relations/company-stock-exchange-announcements). HDFC-group promoter support is an inherited floor, not evidence of an independent ceiling.

---

## SECTION 5 — UNITED STATES ADDITIONAL DISCOVERY BOARD

Exactly ten names passed. Six are mid-cap and/or newly surfaced non-mega-cap candidates; identical confidence and evidence standards were applied to the India board.

| Company | Ticker | Score /100 | Confidence /100 | Category | Main reason to research | Primary risk |
|---|---|---:|---:|---|---|---|
| Kinsale Capital — **RETAINED FROM PRIOR SCREEN** | KNSL | 84 | 88 | Mid-cap specialty-risk Table | **WHY IT REMAINS:** 77.4% Q1 combined ratio and disciplined excess-and-surplus underwriting remain elite versus the cohort | Pricing-cycle reversal, catastrophe/reserve error and 23 July earnings-event risk |
| Cintas — **NEW DISCOVERY** | CTAS | 81 | 92 | Recurring route-density Dealer/Table | FY26 revenue +8.9%; operating income +10.5%; OCF $2.28B less $395M capex implies about $1.89B FCF | Roughly 39x earnings plus UniFirst financing, antitrust and integration risk |
| Hubbell — **RETAINED FROM PRIOR SCREEN** | HUBB | 79 | 88 | Grid critical-supplier Rail | **WHY IT REMAINS:** Q1 sales +11% and utility-infrastructure sales +18% convert the grid theme into revenue | Tariffs, utility project timing, automation softness and valuation |
| Guidewire — **RETAINED FROM PRIOR SCREEN** | GWRE | 79 | 86 | Insurance workflow Dealer → Table | **WHY IT REMAINS:** fiscal Q3 revenue +27%, ARR +19% and raised cash-flow guidance support cloud-migration operating leverage | Migration execution, SBC dilution, concentration and roughly 8x sales |
| S&P Global — **RETAINED FROM PRIOR SCREEN** | SPGI | 79 | 90 | Ratings/data/benchmark House | **WHY IT REMAINS:** ratings, indices and embedded market data retain quaternary standard-setting economics after the Mobility separation | Ratings cycle, AI/data substitution and post-spin comparability |
| NRG Energy — **RETAINED FROM PRIOR SCREEN** | NRG | 78 | 87 | Power Player → Orchestration Dealer | **WHY IT REMAINS:** retail load, generation and virtual-power-plant capability create a path beyond directional generation | LS Power leverage/integration, ERCOT exposure, hedging and regulation |
| Verisk — **NEW DISCOVERY** | VRSK | 78 | 88 | Insurance-data House | Q1 revenue $783M, OCC growth 4.7%, adjusted EBITDA margin about 56%, FCF $326M and a $1.5B accelerated repurchase show converted data economics | Slow growth, leverage/interest cost, buyback timing and insurer budget pressure |
| Broadridge — **NEW DISCOVERY** | BR | 77 | 86 | Governance/settlement Rail | Fiscal Q3 recurring revenue +7% and adjusted EPS +11%; raised FY26 recurring-revenue/EPS outlook reinforces embedded workflow control | Closed sales fell, margin mix, financial-market concentration and regulation |
| Itron — **NEW DISCOVERY** | ITRI | 75 | 83 | Utility-data Pawn → Rook | Q1 Outcomes revenue +22%, adjusted gross margin +490 bps and FCF $79M show software/service mix improving despite lower hardware revenue | Backlog fell to $4.4B, deployment timing, utility procurement, tariffs and acquisitions |
| Core & Main — **NEW DISCOVERY** | CNM | 74 | 82 | Water-infrastructure Distributor/Rail | Fiscal Q1 gross margin +50 bps, net income +7.6% and $82M OCF support a fragmented-network consolidation thesis | Flat sales, housing/municipal cycle, acquisition discipline and working capital |

Evidence anchors: [Cintas FY26](https://www.cintas.com/about/newsroom/details/news/2026/07/15/cintas-corporation-announces-fiscal-2026-fourth-quarter-and-full-year-results/), [Kinsale Q1](https://ir.kinsalecapitalgroup.com/news/news-details/2026/Kinsale-Capital-Group-Reports-First-Quarter-2026-Results/default.aspx), [Hubbell Q1](https://hubbell.gcs-web.com/news-releases/news-release-details/hubbell-reports-first-quarter-2026-results), [Guidewire fiscal Q3](https://ir.guidewire.com/news-releases/news-release-details/guidewire-announces-third-quarter-fiscal-year-2026-financial), [Verisk Q1](https://investor.verisk.com/financials/quarterly-results/default.aspx), [Broadridge fiscal Q3](https://www.broadridge-ir.com/news/news-details/2026/Broadridge-Reports-Third-Quarter-Fiscal-2026-Results/default.aspx), [Itron Q1](https://investors.itron.com/news-releases/news-release-details/itron-announces-first-quarter-2026-financial-results), and [Core & Main fiscal Q1](https://ir.coreandmain.com/news/news-details/2026/Core--Main-Announces-Fiscal-2026-First-Quarter-Results/default.aspx).

---

## SECTION 6 — EARLY-CAPTURE BOARD

Promotion probabilities describe the chance of achieving the stated stronger *business role* within the horizon. They are not target-price probabilities.

### Top 8 India

| Rank | Company | Classification | Current role | Potential future role | Promotion milestones | Probability | Horizon | Major mine | Future already priced? |
|---:|---|---|---|---|---|---:|---|---|---|
| 1 | KFin — **RETAINED FROM PRIOR SCREEN** | DEALER → TABLE | Registrar/servicing Dealer | Multi-jurisdiction asset-servicing Table | >20% organic international growth; clean integrations; near-40% EBITDA margin; durable FCF/share | 70% | 3–5 years | Integration, fee caps and platform/security failure | Partly |
| 2 | Shriram Finance — **NEW DISCOVERY** | PLAYER → DEALER | Specialist balance-sheet lender | Broader underserved-customer credit/distribution Dealer | Cross-sell, diversified liabilities, AUM growth near mid-teens and stable Stage 2/3 credit | 65% | 3–5 years | Used-vehicle/MSME cycle and funding costs | Not fully |
| 3 | IndiaMART — **RETAINED FROM PRIOR SCREEN** | TABLE → HOUSE | B2B discovery Table | Supplier workflow/payment/data House | Supplier reacceleration; Busy >25–30% growth; workflow/transaction revenue; FCF retention | 60% | 3–5 years | Supplier stagnation/churn and weak reinvestment returns | Not fully |
| 4 | VA Tech Wabag — **NEW DISCOVERY** | PAWN → ROOK | Project-based water specialist | Recurring water-treatment/O&M Rail | Framework-to-order conversion; timely collections; recurring O&M rise; positive post-working-capital FCF | 60% | 3–5 years | Sovereign/EPC receivables and execution | Not fully |
| 5 | Indus Towers — **NEW DISCOVERY** | DEALER → TABLE | Passive-infrastructure Dealer/Rail | Multi-tenant digital-infrastructure Table | Tenancy/loading growth; clean Vodafone Idea collections; disciplined overseas returns; sustained FCF | 60% | 3–5 years | Customer concentration and overseas capital allocation | Partly |
| 6 | HDB Financial — **NEW DISCOVERY** | PLAYER → DEALER | Diversified NBFC Player | HDFC-linked multi-product distribution Dealer | Stable GNPA/Stage 3; ROA durability; lower funding cost; cross-sell without credit dilution | 55% | 3–5 years | Unsecured-cycle loss and borrowed parent momentum | Partly |
| 7 | Sagility India — **RETAINED FROM PRIOR SCREEN** | DEALER → TABLE | Healthcare operations Dealer | Payer/provider workflow and outcome Table | Top-client share falls; >12% organic growth; outcome pricing; cash conversion and clean encumbrance | 50% | 3–5 years | Client concentration and ownership/encumbrance | Not fully |
| 8 | Newgen — **RETAINED FROM PRIOR SCREEN** | PAWN → ROOK | Workflow software specialist | Embedded regulated-enterprise process Rail | Recurring/cloud mix; global wins; lower receivable days; >20% FCF conversion | 55% | 3–5 years | Deal lumpiness, platform competition and working capital | Not fully |

### Top 8 United States

| Rank | Company | Classification | Current role | Potential future role | Promotion milestones | Probability | Horizon | Major mine | Future already priced? |
|---:|---|---|---|---|---|---:|---|---|---|
| 1 | Toast — **RETAINED FROM PRIOR SCREEN** | DEALER → TABLE | POS/payment Dealer and Chip | Restaurant/retail commerce Table | >200k locations; >25% recurring gross profit; international/retail attach; durable FCF/share | 70% | 2–4 years | Restaurant cycle, competition, SBC/dilution | Partly |
| 2 | Uber — **RETAINED FROM PRIOR SCREEN** | TABLE → HOUSE | Mobility/delivery Table | Local-commerce and AV-distribution House | Bookings >15%; membership/ads density; AV partner economics; insurance leverage | 65% | 3–5 years | Regulation, insurance and AV bypass | Partly |
| 3 | Guidewire — **RETAINED FROM PRIOR SCREEN** | DEALER → TABLE | Insurance-core software Dealer | P&C workflow/data Table | ARR >15%; migrations; sustained GAAP FCF; lower SBC/share | 65% | 2–4 years | Cloud migration and incumbent/platform competition | Partly |
| 4 | Samsara — **RETAINED FROM PRIOR SCREEN** | PAWN → ROOK | Connected-operations specialist | Physical-operations data Rail | ARR >$2.5B; >25% growth; emerging-product attach; durable per-share FCF | 70% | 2–4 years | Valuation, SBC and hardware/platform rivalry | Meaningfully |
| 5 | Procore — **RETAINED FROM PRIOR SCREEN** | DEALER → TABLE | Construction workflow tool | Collaboration, payments and labor Table | >15% growth; near-20% FCF margin; payments/workforce adoption; retention | 65% | 3–5 years | Construction cycle, seat pressure and SBC | Not fully |
| 6 | Alkami — **RETAINED FROM PRIOR SCREEN** | PAWN → ROOK | Community-bank software specialist | Digital-banking infrastructure Rail | Cross-sell; GAAP profitability/FCF; user growth; clean integrations | 60% | 3–5 years | Debt, bank concentration and SBC | Not fully |
| 7 | Itron — **NEW DISCOVERY** | PAWN → ROOK | Meter/network equipment specialist | Energy/water operational-intelligence Rail | Outcomes >15%; backlog stabilization; recurring mix; repeatable FCF | 55% | 3–5 years | Deployment timing, tariffs and acquisitions | Not fully |
| 8 | NRG Energy — **RETAINED FROM PRIOR SCREEN** | PLAYER → DEALER | Generator/retailer Player | Flexible-load/VPP orchestration Dealer | LS Power integration; debt reduction; VPP scale; repeatable retail margin | 60% | 3–5 years | Leverage, ERCOT, hedging and regulation | Not fully |

The early-capture cut deliberately excludes exciting but pre-conversion names whose survival path requires too many financing, regulatory or technical tiles. Promotion remains conditional until operating and per-share cash evidence arrives.

---

## SECTION 7 — CURRENT HOUSES, TABLES, CHIPS, AND RAILS

### Top 5 India

| Rank | Company | Structural role | Source of economic power / ecosystem earning | Durability | Valuation risk |
|---:|---|---|---|---|---|
| 1 | Power Grid — **RETAINED FROM PRIOR SCREEN** | National transmission House/Rail | Regulated return on commissioned network; paid across renewable, thermal, hydro and storage winners | Very long; grid meshing, right-of-way and state role are hard to replicate | Moderate; capex delays, leverage and allowed-return rules |
| 2 | ICICI Bank — **RETAINED FROM PRIOR SCREEN** | Capital/payment House and Chip | Owns deposits, underwriting, transaction access and direct customer distribution; earns from spreads, fees and payments | Very long; capital and asset quality provide sovereignty | Low/moderate; deposit competition and credit normalization matter more than headline P/E |
| 3 | MCX — **RETAINED FROM PRIOR SCREEN** | Commodity-market House/Table | Controls matching, clearing, liquidity and data; earns regardless of long/short winner | Very long if liquidity and regulatory permission persist | High; excellent economics are partly capitalized and rule risk is binary |
| 4 | Bharti Airtel — **RETAINED FROM PRIOR SCREEN** | Connectivity Rail moving toward Table | Spectrum, network, billing and enterprise distribution monetize voice/data/cloud/payment activity | Very long, tempered by recurring spectrum/capex needs | Moderate/high; debt, African currencies and regulation |
| 5 | Indus Towers — **NEW DISCOVERY** | Passive-network Rail/Dealer | Rent and loading recur across tenant traffic growth without taking handset/content risk | Very long physical half-life; tenancy strengthens network effect | Moderate; customer concentration and overseas reinvestment can impair the discount |

### Top 5 United States

| Rank | Company | Structural role | Source of economic power / ecosystem earning | Durability | Valuation risk |
|---:|---|---|---|---|---|
| 1 | ICE — **RETAINED FROM PRIOR SCREEN** | Exchange/clearing/data/workflow House | Proprietary liquidity, clearing permissions, recurring data and mortgage workflows earn across volatility and transactions | Very long; regulation and embedded workflows raise switching cost | Moderate; debt and mortgage-cycle recovery are required, but the multiple is not heroic |
| 2 | CME Group — **RETAINED FROM PRIOR SCREEN** | Derivatives benchmark and collateral House/Rail | Liquidity, benchmark contracts, margin offsets, clearing and data monetize risk transfer in either direction | Very long; market depth is self-reinforcing | Moderate; ADV and revenue-per-contract normalization |
| 3 | Visa — **RETAINED FROM PRIOR SCREEN** | Payment Chip/Rail/House | Global acceptance, authorization, settlement and value-added services collect across consumer and business commerce | Very long; network ubiquity and trust are formidable | High near the annual high; regulation and alternative rails limit entry odds |
| 4 | BNY — **NEW DISCOVERY** | Custody/settlement/collateral House | $62.6T AUC/A, issuer services, clearance, collateral and payments monetize capital movement independent of security selection | Very long; regulatory trust and scale are institutional | Moderate/high after the earnings gap and around 5x tangible book |
| 5 | Tradeweb — **RETAINED FROM PRIOR SCREEN** | Electronic fixed-income Table | Dealer/client liquidity, execution protocols, data and multi-asset network collect on institutional flow | Very long as electronic penetration compounds | Moderate; share and capture-rate pressure can interrupt the path |

---

## SECTION 8 — COMBINED INDIA + US TOP 20

Scores were compared only after normalizing country-specific valuation, growth, liquidity, rate and market-structure regimes. The resulting 10 India / 10 U.S. split was an output of matched country percentiles—not a quota. Absolute economics and current pot odds prevent a strong national rank from automatically displacing a much better made hand.

| Combined Rank | Company | Ticker | Country | MVP Score | Confidence | Category | Primary Thesis | Primary Risk | Entry Status |
|---:|---|---|---|---:|---:|---|---|---|---|
| 1 | Intercontinental Exchange | ICE | United States | 89 | 90 | Structural House | Multiple clearing, data, energy/rates and workflow rails at a non-heroic multiple | Debt, mortgage cycle and regulation | BUY-RESEARCH ZONE |
| 2 | CME Group | CME | United States | 88 | 91 | Structural House | Proprietary liquidity and clearing monetize volatility in either direction | ADV/capture normalization and rule change | BUY-RESEARCH ZONE |
| 3 | ICICI Bank | ICICIBANK | India | 86 | 89 | Capital/Payment House | Credit growth, clean asset quality and 16%+ CET1 create unusually sovereign compounding | Deposits, NIM and slippage | BUY-RESEARCH ZONE |
| 4 | McKesson | MCK | United States | 87 | 91 | Structural Dealer/Rail | Essential healthcare throughput plus higher-margin oncology/biopharma services | CVS/customer and policy concentration | BUY-RESEARCH ZONE |
| 5 | Tradeweb Markets | TW | United States | 87 | 90 | Table → House | Electronic fixed-income network, data and protocol control compound with share gains | Capture-rate and market-share pressure | BUY-RESEARCH ZONE |
| 6 | HDFC Bank | HDFCBANK | India | 84 | 88 | Capital/Payment House | Post-merger deposit and ROA normalization could close the quality-perception gap | NIM, deposit mix and merger drag | WAIT FOR CATALYST |
| 7 | Uber | UBER | United States | 87 | 90 | Table → House | Marketplace liquidity now converts into EBITDA/FCF while ads, membership and AV add paths | Regulation, insurance and AV bypass | BUY-RESEARCH ZONE |
| 8 | Adobe | ADBE | United States | 87 | 89 | Workflow value dislocation | More than $9B provider TTM FCF and real AI-first ARR at a disruption-level price | AI displacement, ARR deceleration and interim CFO | WAIT FOR CATALYST |
| 9 | Power Grid | POWERGRID | India | 82 | 86 | National Infrastructure Rail | Regulated transmission earns across competing generation technologies | Leverage, capitalization delay and allowed returns | BUY-RESEARCH ZONE |
| 10 | BlackRock | BLK | United States | 86 | 94 | Capital/Data Table | $15.3T AUM, $192B Q2 inflows, Aladdin and private markets deepen multi-rail capture | Market beta, HPS integration and dilution | WAIT FOR PULLBACK |
| 11 | CACI International | CACI | United States | 86 | 89 | Mission Dealer → Rail | $33.4B backlog with EBITDA/FCF growing faster than revenue at a modest forward multiple | Federal timing and ARKA leverage | BUY-RESEARCH ZONE |
| 12 | Shriram Finance | SHRIRAMFIN | India | 82 | 88 | Player → Dealer | Mid-teens AUM and normalized PAT growth can support a broader underserved-customer franchise | Asset quality and funding costs | BUY-RESEARCH ZONE |
| 13 | BNY | BNY | United States | 85 | 95 | Settlement/Collateral House | Fresh Q2 fee growth and 31.3% ROTCE reveal operating leverage in a $62.6T custody rail | Post-gap entry, NII/fee reversal and cyber | WAIT FOR PULLBACK |
| 14 | IndiaMART | INDIAMART | India | 82 | 84 | Table → House | Cash-rich B2B discovery can add supplier workflow and payments without balance-sheet risk | Paying-supplier stagnation and churn | WAIT FOR CATALYST |
| 15 | Copart | CPRT | United States | 84 | 88 | Marketplace House | Yard, insurer, title/logistics and buyer liquidity persist through a unit slowdown | Volume weakness and land returns | WAIT FOR CATALYST |
| 16 | MCX | MCX | India | 81 | 84 | Commodity House/Table | Liquidity, clearing and data are genuine house economics | Rule changes, revenue per contract and overplayed valuation | WAIT FOR CATALYST |
| 17 | KFin Technologies | KFINTECH | India | 81 | 84 | Dealer → Table | Domestic registry plus fast-growing international servicing creates underpriced promotion geometry | Integration and fee regulation | WAIT FOR CATALYST |
| 18 | Bharti Airtel | BHARTIARTL | India | 80 | 86 | Connectivity Rail/Table | ARPU, network density and enterprise/payment distribution deepen economic capture | Spectrum debt, regulation and Africa FX | BUY-RESEARCH ZONE |
| 19 | Indus Towers | INDUSTOWER | India | 80 | 86 | Passive Infrastructure Rail | Conventional FCF and net cash excluding leases support the toll thesis, while lease-inclusive net debt limits the floor | Tenant concentration, lease-adjusted leverage and overseas capex | BUY-RESEARCH ZONE |
| 20 | Oracle Financial Services Software | OFSS | India | 79 | 88 | Banking Workflow Rail | Debt-free, high-margin core-banking software has very-long embedded half-life | Parent dependence, low float and license lumpiness | WAIT FOR PULLBACK |

The score gap is intentionally narrow: these are research priorities, not claims that rank 1 has a materially certain return advantage over rank 10. Country, currency and portfolio-fit risks remain separate allocation decisions. BlackRock enters ahead of Visa because its fresh fee/Aladdin evidence clears the absolute quality hurdle despite a weaker entry; Copart beats Visa on current pot odds; OFSS enters through the matched India percentile plus balance-sheet and half-life quality. These are the principal departures from a mechanical raw-score sort.

---

## SECTION 9 — BEST RISK-ADJUSTED IDEAS

### Top 5 India

| Rank | Company | Why risk-adjusted odds qualify | Valuation / catalyst | Principal survivability check |
|---:|---|---|---|---|
| 1 | ICICI Bank | Best mix of capital, underwriting, growth, sovereignty and low mine density | ATTRACTIVE; next quarter's deposit/NIM evidence | Keep GNPA/NNPA and CET1 strength while deposits fund growth |
| 2 | Power Grid | Regulated cash-earning base and unavoidable national rail diversify away from directional generation bets | ATTRACTIVE; project capitalization and renewable evacuation | Allowed returns and commissioned assets must grow with debt |
| 3 | HDFC Bank | Exceptional franchise at a post-merger valuation discount | ATTRACTIVE; **confirmed Q1 result 18 July** | NIM near/above 3.3%, deposit growth and ROA normalization |
| 4 | Shriram Finance | FY26 AUM +14.9% and normalized PAT +20.9% offer better pot odds than fashionable lenders | ATTRACTIVE; funding/credit-cost normalization | Stage 2/3, collection efficiency and cost of funds |
| 5 | Indus Towers | FY26 conventional FCF ₹3,763 crore and ₹4,932 crore net cash **excluding leases** support traffic growth, but ₹15,274 crore lease-inclusive net debt limits the floor | ATTRACTIVE; tenancy/loading and shareholder returns | Vodafone Idea collections, lease-adjusted leverage and disciplined overseas ROIC |

IndiaMART is the near-miss: its balance sheet and FCF are exceptional, but the paying-supplier engine must reaccelerate before risk-adjusted rank improves.

### Top 5 United States

| Rank | Company | Why risk-adjusted odds qualify | Valuation / catalyst | Principal survivability check |
|---:|---|---|---|---|
| 1 | CME | 72.8% adjusted Q1 operating margin, low leverage intensity and benchmark liquidity produce the lowest mine density among the leading U.S. houses | ATTRACTIVE; **confirmed Q2 22 July** | ADV, share and revenue per contract after elevated volatility |
| 2 | ICE | Diversified clearing/data/workflow rails plus deleveraging reduce dependence on any one volume regime | ATTRACTIVE; **confirmed Q2 30 July** | Data organic growth, mortgage stabilization and debt reduction |
| 3 | Adobe | Real AI ARR and over $9B provider TTM FCF provide a valuation buffer against genuine disruption risk | UNDERVALUED; AI-first ARR and next earnings | Retention, net-new ARR, margins and permanent CFO succession |
| 4 | McKesson | Essential distribution plus $5.4B FY26 FCF and higher-margin service options | ATTRACTIVE; **confirmed fiscal Q1 5 August** | CVS exposure, policy and services-mix conversion |
| 5 | CACI | Backlog, mission relevance and rising FCF at about 15x provider forward earnings | UNDERVALUED; **confirmed FY26/FY27 guide 5 August** | Book-to-bill, award timing and ARKA leverage |

BNY is the near-miss: evidence quality is highest in the screen, but the 5.1% post-result gap weakens today's entry odds.

---

## SECTION 10 — HIGH UPSIDE, HIGH MINE DENSITY

These are research candidates, **not high-conviction recommendations**. Survival probability is a subjective thesis estimate, not a statistical forecast.

### India — up to 5

| Company | Theoretical upside if promotion works | Milestones required | Hidden mines | Thesis-survival probability | Evidence required before investment |
|---|---|---|---|---:|---|
| PB Fintech — **RETAINED FROM PRIOR SCREEN** | Insurance/credit marketplace could become a multi-product financial Table/House | Renewal profit, claims economics, non-insurance contribution, durable per-share FCF | Regulation, credit loss, SBC/dilution, insurer bargaining and valuation | 55% | Two clean quarters of per-share FCF and transparent cohort/claims economics |
| Angel One — **NEW DISCOVERY** | Broker could become a wealth/AMC/insurance/credit Table | Non-broking mix, stable client-funding losses, margin recovery and FCF/share | Trading cyclicality, SEBI rules, credit book, ESOPs and QoQ profit reversal | 55% | Clean regulatory quarters, segment profit and diluted FCF/share |
| Kaynes Technology — **RETAINED FROM PRIOR SCREEN** | EMS specialist could become a semiconductor/critical-electronics Rail | OSAT customer qualification, utilization, funding closure and product mix | Deeply negative FY26 FCF, capex, execution, dilution/debt and rich multiple | 35% | Audited customer qualification, funded capex and positive post-capex FCF path |
| Himadri Speciality Chemical — **NEW DISCOVERY** | Specialty carbon plus anode materials could create an integrated battery-material Rook | Plant commissioning, export qualification, high utilization and return above cost of capital | Technology/yield, commodity inputs, capex, customer concentration and valuation | 45% | Signed customers, qualification yields and post-expansion cash conversion |
| Solar Industries — **RETAINED FROM PRIOR SCREEN** | Industrial explosives platform could expand into a scaled defence Bishop/Rook | Order conversion, approvals, capacity and defence cash margin | Near-100x trailing earnings, safety, regulation, working capital and narrative crowding | 25% at current entry | Defence segment FCF, delivery record and a valuation reset |

### United States — up to 5

| Company | Theoretical upside if promotion works | Milestones required | Hidden mines | Thesis-survival probability | Evidence required before investment |
|---|---|---|---|---:|---|
| AST SpaceMobile — **NEW DISCOVERY** | Direct-to-device could become a global telecom layer | Satellite cadence, commercial service revenue, uptime and partner unit economics | Launch/technical failure, capex, competition, dilution and proposed $1B convertible plus $150M option | 30% | Recurring service revenue, funded constellation and measured network performance |
| Rocket Lab — **RETAINED FROM PRIOR SCREEN** | Neutron plus space systems could create an integrated space-infrastructure Rook | Successful Neutron flight/cadence, margin expansion and contracted unit economics | Mission failure/delay, cash burn, capex and dilution despite $2.2B Q1 backlog | 35% | Flight evidence, repeat launches and credible positive FCF bridge |
| Applied Digital — **RETAINED FROM PRIOR SCREEN** | Energized campuses could turn construction risk into long-lived AI-infrastructure rent | Site finance, energization, tenant acceptance and cash NOI | Construction/debt, tenant concentration, refinancing and roughly $1.5B provider negative FCF | 30% | Site-level funding, audited rent/NOI and tenant diversification |
| Tempus AI — **RETAINED FROM PRIOR SCREEN** | Diagnostics plus multimodal clinical data could become an oncology data standard | Organic data growth, reimbursement, GAAP leverage and FCF/share | Net loss, SBC, integrations, privacy, debt and valuation | 45% | Organic growth excluding acquisitions and diluted FCF/share |
| Hims & Hers — **RETAINED FROM PRIOR SCREEN** | Consumer-health distribution could scale across conditions and countries | U.S. recovery, retention, branded drug economics, Eucalyptus integration and FDA clarity | Q1 net loss, gross-margin fall, GLP-1 supply/regulation, CAC and convertible debt | 45% | Cohort retention, U.S. organic recovery and recurring FCF excluding working-capital timing |

ASTS closed at $66.31 on 15 July; its convertible announcement followed the close, so the next executable price was unknown at analysis time: **LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT**. Evidence: [ASTS financing release](https://www.businesswire.com/news/home/20260715000369/en/AST-SpaceMobile-Announces-Proposed-Private-Offering-of-%241.0-Billion-of-Convertible-Senior-Notes-Due-2034), [Rocket Lab Q1](https://investors.rocketlabcorp.com/news-releases/news-release-details/rocket-lab-announces-first-quarter-2026-financial-results), [Applied Digital fiscal Q3](https://ir.applieddigital.com/news-events/press-releases/detail/148/applied-digital-reports-fiscal-third-quarter-2026-results), [Tempus Q1](https://investors.tempus.com/news-releases/news-release-details/tempus-reports-first-quarter-2026-results), and [Hims Q1](https://investors.hims.com/news/news-details/2026/Hims--Hers-Health-Inc--Reports-First-Quarter-2026-Financial-Results/default.aspx).

---

## SECTION 11 — QUEEN-PRICED PAWNS

Every row carries `VALUATION CAUTION`. It is a price/evidence warning, not a claim that the product or company is poor.

### India

| Company | Freshness | Why expectations outrun the made hand | Promotion tiles still required | Label |
|---|---|---|---|---|
| Eternal | RETAINED FROM PRIOR SCREEN | Vendor snapshot near 718x trailing and 72x forward earnings while standardized provider FCF remains negative; quick-commerce scale is not yet house-level cash economics | Sustainable contribution margin, consolidated FCF/share and proof logistics intensity falls with scale | `VALUATION CAUTION` |
| Amber Enterprises | **NEW DISCOVERY** | Vendor multiple near 150x trailing earnings and negative recent FCF already capitalizes cooling/electronics platform migration | Higher-value electronics mix, working-capital control and post-capex FCF | `VALUATION CAUTION` |
| Netweb Technologies | RETAINED FROM PRIOR SCREEN | Around 118x provider trailing earnings and 34x book price server growth like a recurring data rail | Recurring service/software mix, durable margins, FCF and customer diversification | `VALUATION CAUTION` |
| Solar Industries | RETAINED FROM PRIOR SCREEN | Around 99x trailing earnings assumes successful defence expansion on top of industrial explosives quality | Delivery, defence cash conversion, safe capacity ramp and export evidence | `VALUATION CAUTION` |
| Kaynes Technology | RETAINED FROM PRIOR SCREEN | Around 61x earnings while FY26 FCF was materially negative; OSAT success is substantially anticipated | Qualified customers, utilization, fully funded capex and positive post-capex FCF | `VALUATION CAUTION` |

### United States

| Company | Freshness | 15 July price / approximate cap | Why expectations outrun the made hand | Label |
|---|---|---|---|---|
| AST SpaceMobile | **NEW DISCOVERY** | $66.31 / $25.7B | Roughly $85M provider TTM revenue, deeply negative FCF and a proposed $1B convertible precede commercial constellation proof | `VALUATION CAUTION` |
| Rocket Lab | RETAINED FROM PRIOR SCREEN | $76.20 / $47.6B | Q1 execution is real, but Neutron success/cadence and high long-run margins are already heavily capitalized versus $200M quarterly revenue | `VALUATION CAUTION` |
| Palantir | RETAINED FROM PRIOR SCREEN | $133.76 / $320.7B | A superb made hand becomes overplayed near roughly 60x EV/revenue and 149x trailing earnings | `VALUATION CAUTION` |
| Robinhood | RETAINED FROM PRIOR SCREEN | $115.54 / $104.0B | Financial-house migration is priced as durable despite crypto/transaction cyclicality and regulatory range | `VALUATION CAUTION` |
| CoreWeave | RETAINED FROM PRIOR SCREEN | $77.12 / $42.1B | Large backlog is not low-risk cash: provider debt near $35B and deeply negative FCF create correlated financing/tenant mines | `VALUATION CAUTION` |
| Tempus AI | RETAINED FROM PRIOR SCREEN | $57.25 / $10.3B | 36% Q1 growth is encouraging, but GAAP loss, SBC and integration risk remain ahead of data-standard economics | `VALUATION CAUTION` |
| IonQ | RETAINED FROM PRIOR SCREEN | $37.51 / $14.0B | Commercial revenue and cash generation remain tiny relative to a valuation assuming useful scaled quantum demand | `VALUATION CAUTION` |

Primary evidence for the U.S. caution set: [Palantir Q1](https://www.sec.gov/Archives/edgar/data/1321655/000132165526000026/a2026q1ex991pressrelease.htm), [Robinhood Q1](https://investors.robinhood.com/news-releases/news-release-details/robinhood-reports-first-quarter-2026-results), [CoreWeave Q1](https://investors.coreweave.com/news/news-details/2026/CoreWeave-Reports-Strong-First-Quarter-2026-Results/), [Tempus Q1](https://investors.tempus.com/news-releases/news-release-details/tempus-reports-first-quarter-2026-results), and [IonQ Q1](https://investors.ionq.com/news/news-details/2026/IonQ-Announces-First-Quarter-2026-Financial-Results/default.aspx). Vendor valuation fields remain subject to provider-methodology differences.

### Non-primary candidate score registry

Every named investable company that was not already scored in the 30 primary or 20 additional-candidate tables is scored here. This prevents a high-mine or caution name from escaping the same 100-point hurdle merely because it sits outside the main ranking.

| Country | Company | Ticker | Freshness | MVP Score /100 | Confidence /100 | Dominant current classification |
|---|---|---|---|---:|---:|---|
| India | Sagility India | SAGILITY | RETAINED FROM PRIOR SCREEN | 76 | 80 | RESEARCH DEEPER |
| India | Polycab India | POLYCAB | RETAINED FROM PRIOR SCREEN | 79 | 86 | GOOD COMPANY — EXPENSIVE PRICE |
| India | PB Fintech | PBFINTECH | RETAINED FROM PRIOR SCREEN | 73 | 83 | HIGH UPSIDE — HIGH MINE DENSITY |
| India | Solar Industries | SOLARINDS | RETAINED FROM PRIOR SCREEN | 72 | 84 | VALUATION CAUTION |
| India | Kaynes Technology | KAYNES | RETAINED FROM PRIOR SCREEN | 68 | 80 | HIGH UPSIDE — HIGH MINE DENSITY |
| India | Eternal | ETERNAL | RETAINED FROM PRIOR SCREEN | 67 | 80 | VALUATION CAUTION |
| India | KPIT Technologies | KPITTECH | RETAINED FROM PRIOR SCREEN | 66 | 86 | THESIS WEAKENING |
| India | Netweb Technologies | NETWEB | RETAINED FROM PRIOR SCREEN | 65 | 78 | VALUATION CAUTION |
| India | Amber Enterprises | AMBER | **NEW DISCOVERY** | 63 | 76 | VALUATION CAUTION |
| United States | Samsara | IOT | RETAINED FROM PRIOR SCREEN | 76 | 88 | EARLY CAPTURE |
| United States | Procore | PCOR | RETAINED FROM PRIOR SCREEN | 76 | 86 | EARLY CAPTURE |
| United States | Alkami | ALKT | RETAINED FROM PRIOR SCREEN | 74 | 85 | EARLY CAPTURE |
| United States | Hims & Hers | HIMS | RETAINED FROM PRIOR SCREEN | 65 | 86 | HIGH UPSIDE — HIGH MINE DENSITY |
| United States | Palantir | PLTR | RETAINED FROM PRIOR SCREEN | 70 | 92 | GOOD COMPANY — EXPENSIVE PRICE |
| United States | Robinhood | HOOD | RETAINED FROM PRIOR SCREEN | 68 | 89 | VALUATION CAUTION |
| United States | Rocket Lab | RKLB | RETAINED FROM PRIOR SCREEN | 66 | 88 | HIGH UPSIDE — HIGH MINE DENSITY |
| United States | Tempus AI | TEM | RETAINED FROM PRIOR SCREEN | 66 | 84 | HIGH UPSIDE — HIGH MINE DENSITY |
| United States | Applied Digital | APLD | RETAINED FROM PRIOR SCREEN | 62 | 83 | HIGH UPSIDE — HIGH MINE DENSITY |
| United States | CoreWeave | CRWV | RETAINED FROM PRIOR SCREEN | 58 | 88 | VALUATION CAUTION |
| United States | AST SpaceMobile | ASTS | **NEW DISCOVERY** | 55 | 79 | HIGH UPSIDE — HIGH MINE DENSITY |
| United States | IonQ | IONQ | RETAINED FROM PRIOR SCREEN | 54 | 87 | VALUATION CAUTION |

---

## SECTION 12 — FALSE-PATTERN AND HYPE TRAPS

| Market narrative | Market | Filter classification | Why the analogy may fail | Evidence that would change the verdict |
|---|---|---|---|---|
| “Every defence/rail order book becomes the next multibagger” | India | Survivorship bias / weak analogy | Orders can be low-margin, delayed, import-dependent and working-capital hungry; revenue is not FCF | Delivery cadence, cash collections, ROCE and customer diversification |
| “Every EMS/OSAT company becomes India's semiconductor champion” | India | Narrative copy | Assembly scale does not prove yields, process IP, utilization or capital sovereignty | Qualified global customers, yields, funded capex and post-capex FCF |
| “Digital India makes every broker/fintech a House” | India | Weak analogy | The regulator owns permission; trading volumes and client funding can reverse together | Diversified recurring profit, clean credit and diluted FCF/share |
| “PSU rerating must continue because it already worked” | India | Gambler's fallacy | Prior rerating says nothing about incremental ROE, governance or today's entry multiple | Reform-linked capital allocation and earnings exceeding cost of capital |
| “Data-centre demand makes every electrical/server supplier a data rail” | India | Narrative copy | Project revenue and hardware margin lack recurring control over workloads/data | Installed-base service revenue, switching cost and repeatable FCF |
| “A fallen IT stock is due to bounce” | India | Gambler's fallacy | Price decline alone does not repair client budgets, growth or margin | Two quarters of revenue acceleration, book-to-bill and cash conversion |
| “Every AI application becomes Palantir” | United States | Survivorship bias / narrative copy | Distribution, proprietary data, security clearance, pricing and FCF differ materially | Durable net retention, per-share FCF and unique data/workflow control |
| “Every space company becomes SpaceX” | United States | Weak analogy | Launch reliability, vertical integration, capital access and cadence are not transferable labels | Repeated missions, funded deployment, unit economics and service revenue |
| “AI power demand guarantees every generator/data-centre developer wins” | United States | Structural theme, weak stock analogy | Financing, interconnection, tenant and commodity risks determine who captures value | Energized capacity, contracted cash rent and balance-sheet-contained funding |
| “Optical/server suppliers are all the next Nvidia” | United States | Narrative copy | Component competition, customer concentration and inventory cycles prevent platform economics | Proprietary standards, multi-customer share and FCF through a down-cycle |
| “GLP-1 telehealth automatically becomes a healthcare House” | United States | Weak analogy | Drug IP, FDA permission, supply and acquisition costs may remain outside the platform's control | Branded economics, retention, regulatory clarity and multi-condition FCF |
| “Backlog equals annuity revenue” | United States | False conversion | Cancellation, construction, financing and customer-concentration tiles stand between backlog and cash | Non-cancellable contracts, funded capex, acceptance and audited NOI/FCF |

The most important distinction is mechanism: grid investment and exchange electronification are structural patterns; blanket stock extrapolation inside those themes is not.

---

## SECTION 13 — ACTION BOARD

### Catalyst map

| Horizon | India | United States | Evidence class |
|---|---|---|---|
| 7 days | HDFC Bank Q1 on 18 July; monitor Angel/HDB/Himadri post-result price discovery | CME Q2 on 22 July; Kinsale Q2 on 23 July | HDFC/CME/KNSL dates **CONFIRMED**; price reaction unknown |
| 30 days | Q1 reporting for the remaining primary cohort; Power Grid/L&T capitalization and order updates | Visa 28 July; Veralto 29 July; ICE/Tradeweb/Tempus 30 July; Uber, McKesson and CACI 5 August | Named U.S. result dates **CONFIRMED** where stated; operating outcomes unknown |
| 90 days | IndiaMART supplier/Busy trend; Wabag framework conversion; KFin organic international growth | Copart units/pricing; Adobe AI-first ARR; Guidewire migrations; ASTS financing/deployment update | **PROBABLE** operating checkpoints; ASTS timing partly speculative |
| 6 months | Telecom loading/cash returns; HDFC normalization; Shriram credit costs; Wabag collections | ICE deleveraging; BNY platform margin; Toast retail/international attach; NRG integration/debt | **PROBABLE** thesis milestones |
| 12 months | Regulated grid capitalization, financialization rails and water O&M conversion | AV distribution economics, insurance-cloud conversion, Neutron execution and AI-data FCF | **SPECULATIVE** until contracts, results or launches confirm |

### India actions

| Action | Candidates |
|---|---|
| STRUCTURAL COMPOUNDER | ICICI Bank; Power Grid; Bharti Airtel; Indus Towers |
| HIGH-CONVICTION RESEARCH CANDIDATE | Shriram Finance; Larsen & Toubro |
| EARLY CAPTURE | KFin Technologies; VA Tech Wabag; HDB Financial; Newgen |
| RESEARCH DEEPER | Adani Ports; Gravita India; Sagility India |
| WATCHLIST | HDFC Life; CAMS; CDSL |
| WAIT FOR ENTRY | HDFC Asset Management |
| WAIT FOR PULLBACK | OFSS; Sun Pharma |
| WAIT FOR CATALYST | HDFC Bank; MCX; IndiaMART; Persistent Systems; Reliance Industries |
| GOOD COMPANY — EXPENSIVE PRICE | Polycab |
| HIGH UPSIDE — HIGH MINE DENSITY | PB Fintech; Angel One; Kaynes; Himadri; Solar Industries |
| VALUATION CAUTION | Eternal; Amber; Netweb |
| THESIS WEAKENING | KPIT Technologies until growth guidance stabilizes |
| AVOID | Unverified, illiquid theme microcaps and any issuer failing governance/pledge/auditor gates |
| DATA INSUFFICIENT | Names without current promoter pledge, auditor, related-party or executable-price validation |

### United States actions

| Action | Candidates |
|---|---|
| STRUCTURAL COMPOUNDER | ICE; CME; McKesson; Veralto; MSA Safety |
| HIGH-CONVICTION RESEARCH CANDIDATE | Uber; CACI; Tradeweb |
| EARLY CAPTURE | Toast; Guidewire; Procore; Alkami; Itron; NRG |
| RESEARCH DEEPER | Verisk; Broadridge; Core & Main |
| WATCHLIST | Kinsale; Hubbell; S&P Global |
| WAIT FOR ENTRY | Cintas |
| WAIT FOR PULLBACK | BlackRock; Visa; BNY after the result gap |
| WAIT FOR CATALYST | Adobe; Veeva; Copart |
| GOOD COMPANY — EXPENSIVE PRICE | Palantir |
| HIGH UPSIDE — HIGH MINE DENSITY | AST SpaceMobile; Rocket Lab; Applied Digital; Tempus; Hims & Hers |
| VALUATION CAUTION | IonQ; CoreWeave; Robinhood |
| THESIS WEAKENING | Managed-care names until medical-cost trends stabilize |
| AVOID | Pre-revenue social-hype names lacking funded milestones or audited commercial evidence |
| DATA INSUFFICIENT | Any candidate lacking refreshed Form 4, institutional-position or next executable-price validation |

An issuer can be structurally excellent and still have a current `WAIT FOR PULLBACK` action. The action is about today's research/entry posture, not a permanent company label.

---

# FINAL DAILY SYNTHESIS

The strongest made edges today are **ICE, CME, ICICI Bank, McKesson, Power Grid and CACI**. The best underpriced promotion paths are **KFin, Shriram Finance, Toast and Wabag**. The largest theoretical multipliers sit elsewhere—and carry materially worse survival odds.

## Selections 1–15

| No. | Required selection | Winner | Why it ranks here | What the market may be missing | Main catalyst | Main invalidation | Evidence required next |
|---:|---|---|---|---|---|---|---|
| 1 | BEST INDIA OPPORTUNITY TODAY | **ICICI Bank** | Highest India score: growth, capital, clean asset quality, customer ownership and reasonable pot odds | Quality can persist without a heroic credit or rate assumption | Q1 deposit growth, NIM and slippage | Sustained NIM below ~4%, material slippage or deposits lagging credit | Fresh Q1 capital, deposit, loan, NPA and restructured-book bridge |
| 2 | BEST US OPPORTUNITY TODAY | **ICE** | Best overall score and diversified house economics at a defensible valuation | Mortgage weakness obscures clearing, energy/rates, data and workflow compounding | **Confirmed Q2 on 30 July** | Data slowdown, exchange share/capture loss or deleveraging failure | Segment organic growth, mortgage revenue, FCF and net-debt bridge |
| 3 | BEST INDIA EARLY-CAPTURE OPPORTUNITY | **KFin Technologies** | 70% estimated Dealer→Table path, converted international growth and positive FCF | The market may still frame it as a domestic registrar rather than global asset servicing | Organic international growth and integration updates | Organic growth falls, integration slips or fee caps compress economics | Acquisition-separated growth, retention, margin and diluted FCF/share |
| 4 | BEST US EARLY-CAPTURE OPPORTUNITY | **Toast** | 26% ARR growth, 22% location growth and positive FCF support real Dealer→Table conversion | Retail, international, payroll and capital attach can widen value per location | Next result and attach-rate disclosure | Location/GPV growth below mid-teens or SBC blocks per-share conversion | Cohort retention, recurring gross profit, SBC/share and international unit economics |
| 5 | BEST INDIA STRUCTURAL HOUSE/TABLE/RAIL | **Power Grid** | An unavoidable regulated transmission rail earns across competing energy winners | Renewable evacuation converts capex into a larger regulated base rather than a directional power bet | Project capitalization and awards | Allowed-return damage, persistent commissioning delay or debt outruns earnings | Project-by-project capitalization, CWIP, leverage and regulated-return schedule |
| 6 | BEST US STRUCTURAL HOUSE/TABLE/RAIL | **ICE** | Clearing permission, proprietary liquidity, data and embedded workflow form the broadest house in the screen | Four reinforcing rails make results less volume-dependent than an exchange label implies | **Confirmed Q2 on 30 July** | Regulatory economics change or recurring data loses pricing/share | Data retention/organic growth, clearing share and mortgage workflow recovery |
| 7 | BEST INDIA RISK-ADJUSTED OPPORTUNITY | **ICICI Bank** | Highest combination of sovereignty, valuation, evidence and mine survival | A clean balance sheet means upside need not rely on repair | Q1 deposit/NIM evidence | Deposit franchise weakens or credit cost normalizes sharply higher | Deposit cohorts, LCR, CET1, credit cost and segment ROA |
| 8 | BEST US RISK-ADJUSTED OPPORTUNITY | **CME Group** | Extraordinary margins, benchmark liquidity, clearing and lower mine density than high-growth alternatives | Volatility need not rise for electronification, product depth and data to compound | **Confirmed Q2 on 22 July** | Persistent ADV/share loss or revenue-per-contract deterioration | Product-level ADV, open interest, capture, expenses and capital return |
| 9 | HIGHEST-UPSIDE INDIA CANDIDATE | **Kaynes Technology** | A successful OSAT/critical-electronics promotion can expand both addressable market and strategic role | Theoretical platform value exceeds today's EMS role—but only after qualification and utilization | Customer qualification and capex commissioning | Funding stress, delay, low utilization or persistent negative post-capex FCF | Binding customers, yield/utilization, funding stack and audited FCF bridge |
| 10 | HIGHEST-UPSIDE US CANDIDATE | **AST SpaceMobile** | Direct-to-device service could become a global telecom layer | Partner distribution can compress customer-acquisition needs if the constellation works | Funding terms, launch cadence and first recurring commercial revenue | Launch/technical failure, underfunding or dilution overwhelms per-share value | Next executable price, final convertible terms, uptime, service revenue and funded deployment |
| 11 | MOST ATTRACTIVELY VALUED INDIA CANDIDATE | **HDFC Bank** | Post-merger valuation discounts weaker economics despite exceptional deposits, capital and distribution | ROA/NIM normalization may be closer than sentiment assumes | **Confirmed Q1 on 18 July** | NIM below ~3.3%, deposits disappoint or merger drag persists | Q1 average-balance NIM, deposit mix, ROA, costs and asset quality |
| 12 | MOST ATTRACTIVELY VALUED US CANDIDATE | **Adobe** | About 12.5x GAAP or 9.2x company-guided non-GAAP FY26 EPS at $224.56, with substantial FCF | AI-first ARR above $500M suggests adoption and displacement can coexist | AI ARR, retention and permanent CFO succession | ARR deceleration, margin damage or AI erodes pricing/retention | Product-level AI ARR, renewal cohorts, seats, FCF and succession announcement |
| 13 | MOST OVERPRICED PAWN | **IonQ** | Approximately $14B value is far ahead of present commercial revenue and operating cash evidence | Technical progress is not yet a repeatable cash-generating standard | Commercial bookings/revenue and error-correction evidence | This caution fails if scaled customer use and positive unit economics arrive much sooner | Customer-level production workloads, bookings conversion, cash burn and dilution |
| 14 | MOST IMPORTANT NEW INDIA DISCOVERY | **Shriram Finance** | FY26 AUM +14.9% and normalized PAT +20.9% at attractive pot odds create a fresh quality/value mix | The franchise may be evolving beyond specialist vehicle lending | Funding-cost/credit-cost normalization and cross-sell | Stage 2/3 rises, collections weaken or funding advantage disappears | Segment AUM, vintages, Stage 2/3, yields, funding and capital ratios |
| 15 | MOST IMPORTANT NEW US DISCOVERY | **BNY** | Q2 revenue +13%, EPS +27%, 39.8% pretax margin and 31.3% ROTCE reveal converted platform leverage | It remains perceived as a rate-sensitive custodian rather than settlement/collateral infrastructure | Fee-led platform growth after the Q2 gap | Organic fee growth slows, margins reverse, CET1 pressure or a cyber event | Organic fee/NII bridge, platform expenses, CET1, buybacks and post-gap price support |

The highest-upside selections are intentionally **not** the best opportunities: Kaynes and ASTS require several correlated Mines tiles, while ICICI and ICE already possess made hands.

## 16. TOP 10 COMPANIES REQUIRING IMMEDIATE DEEPER RESEARCH

| Priority | Company | Why immediate | What the market may be missing | Main catalyst | Invalidation | Evidence required next |
|---:|---|---|---|---|---|---|
| 1 | HDFC Bank | Q1 is two days away and can resolve the post-merger normalization debate | Average-balance economics may improve faster than reported-period sentiment | 18 July result | Weak deposits, sub-3.3% NIM or no ROA progress | Full Q1 deck, average balances, deposit mix and management bridge |
| 2 | CME Group | High-quality house with a confirmed result inside one week | Product breadth and collateral efficiency may offset ADV normalization | 22 July result | Share/capture loss or expense surprise | ADV/open-interest by product, capture and guidance |
| 3 | KFin Technologies | Best India promotion geometry with integration complexity | Organic international servicing could become the independent ceiling | Next organic/integration disclosure | Acquisition-only growth or margin/retention slippage | Organic/constant-currency growth, churn, margin and FCF/share |
| 4 | VA Tech Wabag | New water-rail candidate with ₹17,200+ crore order book and net cash | Recurring O&M and technology economics may be hidden by EPC classification | Framework conversion and quarterly collections | Receivable stress or order conversion stalls | Customer/order aging, cash collections, O&M share and post-WC FCF |
| 5 | Shriram Finance | Fresh quality/value candidate needs credit-vintage verification | Diversification may reduce the historical specialist-lender discount | Quarterly credit/funding update | Stage 2/3 or cost of funds rises materially | Vintages, collections, Stage 2/3, ECL and ALM schedule |
| 6 | BNY | Fresh Q2 operating evidence is excellent but the stock gapped 5.1% | Platform operating leverage may be durable beyond rate support | Post-result follow-through and next monthly/quarterly data | Fee/margin reversal or capital pressure | Organic fee bridge, NII sensitivity, CET1 and technical gap support |
| 7 | Adobe | Valuation says structural impairment while AI ARR says partial conversion | AI can be an upsell and retention tool, not only a substitute | Next AI ARR update and CFO appointment | Net-new ARR/retention weakens or margins fall | Cohort retention, product attach, inference cost, SBC and FCF |
| 8 | BlackRock | Q2 gap followed 31% revenue growth, $15.3T AUM and $192B inflows | Aladdin/private markets may raise fee durability beyond ETF beta | HPS integration and Aladdin ACV | Integration failure, organic fee weakness or dilution offsets growth | Base-fee organic growth, HPS margins, Aladdin ACV and diluted share count |
| 9 | Copart | High-sovereignty marketplace is in a unit-growth pause | Yard density and global buyer liquidity can compound even before units recover | Unit/pricing stabilization | Units stay weak without price/share gains or land ROIC falls | Units, revenue per unit, insurer share, capex and land returns |
| 10 | Indus Towers | New value-backed rail with conventional FCF and net cash excluding leases, tempered by lease-inclusive net debt | Traffic/loading and overseas reuse can extend the cash runway | Tenancy/loading and capital-return update | Vodafone Idea collections fail, lease-adjusted leverage worsens or overseas capex destroys ROIC | Tenant receivables, tower/colocation adds, loading, lease liabilities, capex and payout policy |

## Closing judgment

Today's best answer to the Sleeping Passenger question is **not** the name with the loudest multiplier. It is the cluster where control, cash conversion, sovereignty and valuation overlap: **ICE, CME, ICICI Bank, Power Grid, McKesson and CACI**. For earlier capture, **KFin, Shriram Finance, Toast and Wabag** offer the cleanest evidence-to-promotion balance. **ASTS, Kaynes, Rocket Lab, Solar and Applied Digital** may offer larger theoretical outcomes, but their correlated financing/execution/valuation mines make them research options rather than core ideas.

No investment is guaranteed. This is an advisory research screen, not individualized investment advice or a direction to trade. Revalidate executable price, ownership/governance, filings, currency, taxes and portfolio concentration before any decision.
