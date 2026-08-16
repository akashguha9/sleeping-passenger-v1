# Sleeping Passenger — India + United States Matrix Winner Discovery

> **Advisory research only. No investment is guaranteed.** Scores rank research priority and weighted evidence; they are not target returns or trade instructions.

> `LIVE VALIDATION REQUIRED` for executable prices, promoter/pledge and related-party fields, current Form 4/13F activity, complete estimate revisions, and any ownership field not explicitly linked to a current filing.

## 1. Analysis Metadata

- **Analysis date:** 2026-07-27
- **Generation time:** 2026-07-27 17:13:44 India Standard Time+0530, Asia/Calcutta
- **India market status:** **CLOSED — 27 July regular session complete; official 15:30 close validated**
- **United States market status:** **PRE-MARKET — latest validated regular-session close is 24 July**
- **Scope:** India—NSE/BSE; United States—NYSE, Nasdaq and NYSE American. Foreign ADRs and every other country are excluded.
- **Equal-depth rule:** 15 India and 15 US primary candidates; 10 India and 10 US additional discoveries; every segment has separate India and US fields.
- **Price basis:** India primary prices are 27 July NSE closes and US primary prices are 24 July regular-session closes, refreshed through Yahoo/yfinance. The official NSE index map is the 27 July 15:30 IST close. They are dated reference observations, not executable bids/offers.
- **Data sources:** [official NSE all-indices feed](https://www.nseindia.com/api/allIndices), Yahoo/yfinance read-only OHLCV, [SEC EDGAR](https://www.sec.gov/edgar/search/), company investor-relations releases and the sourced [fully sourced discovery evidence spine](daily_stock_discovery_2026-07-16.md), plus the official 18–27 July result releases linked in the evidence delta.
- **Financial periods:** India FY2025-26/Q1 FY2026-27 where released; US Q1/Q2/FY2026 as identified in each linked release.
- **Confidence:** separate from opportunity. It discounts stale fields, source disagreement, transparency gaps, limited samples and forecast uncertainty.
- **GICS:** all 11 official broad sectors are used. Industry group/industry/sub-industry are working GICS-normalized mappings and should be rechecked against a licensed constituent file before production use.

### Repository recovery and discipline

- Branch: `sprint/open-the-gate-gap-closer`.
- Baseline worktree was already dirty: six tracked files modified plus prior reports and `tmp/` untracked. Those changes were preserved.
- Reused: `fresh_market_discovery.py`, `daily_scoring.py`, `minimum_daily_universe.py`, market/Yahoo adapters, ticker resolution, OHLCV utilities, and prior report conventions.
- Existing isolated 100-point matrix builder and 16 July evidence spine were reused; no production application code was modified.
- Change made: the isolated report builder was minimally refreshed for 27 July prices, market maps, released-event deltas, scoring and validation metadata; no commit or push.
- Live-source audit: the official NSE all-indices feed returned the 27 July 15:30 close and Yahoo returned 27 July India/24 July US reference closes for all 30 primaries. The repository's 24 July daily payload is `STATIC_UNIVERSE_FALLBACK`/`UNVERIFIED`, so it was excluded as live evidence.
- Dependency audit: Python and the existing yfinance/pandas report path executed successfully. Report syntax, JSON parsing, CSV rows and matrix invariants are validated by the builder.

### Data limitations

No consolidated real-time feed/order book, full estimate-history database, uniformly current promoter/insider/institutional feed, or active multi-provider quote fallback was available. India promoter encumbrance, FII/DII, auditor/RPT and free-float fields, and US SBC/Form 4/customer/cloud concentration fields were included only when filing-supported; otherwise they remain a next-evidence gate. Bank/NBFC/insurer conventional FCF is not used as though it were industrial-company FCF.

## 2. India Market Map

- **Condition:** broad relief rally after five losing sessions. At the official 27 July 15:30 IST close, Nifty 50 was **+0.96%**, Nifty 500 **+1.05%**, Midcap 100 **+1.11%**, and Nifty 500 breadth was **387 advances / 110 declines**; India VIX was **12.66 (-9.76%)**. [Official NSE feed](https://www.nseindia.com/api/allIndices)
- **Leadership:** IT **+2.34%**, Realty **+2.28%**, Pharma **+1.56%**, Health Care **+1.46%** and Auto **+1.60%** led; all tracked sector indices were positive.
- **Macro drivers:** the pause in US–Iran strikes and a sharp oil decline reduced India's import/inflation risk for the session; earnings dispersion and INR/rate sensitivity remain the next filters. [27 July market wrap](https://upstox.com/news/market-news/stocks/market-wrap-july-27-sensex-jumps-776-pts-nifty-50-ends-at-23-996-led-by-it-bank-stocks-as-crude-oil-prices-decline-eternal-indi-go-top-gainers/article-197620/)
- **Fresh evidence gates:** ICICI's Q1 release passed the NIM/capital/asset-quality gate; HDFC Bank's 3.26% NIM breached this screen's prior 3.3% invalidation; KFin's 34.2% EBITDA margin breached its prior 38% gate despite revenue growth. [ICICI Q1](https://www.icici.bank.in/about-us/news-room/2026/performance-review-quarter-ended-june-30-2026), [HDFC result archive](https://www.hdfc.bank.in/about-us/investor-relations/financial-results), [KFin Q1 KPI](https://investor.kfintech.com/quarterly-key-performance-indicators/)
- **Strongest areas:** well-capitalized lenders; capital-market/registry rails; transmission; telecom towers/data; water infrastructure; selective digital engineering; auto only where cash and share evidence convert.
- **Avoid/discount:** leveraged renewables, order-book stories without cash, weak-governance microcaps, oil-sensitive airlines and queen-priced EMS/semiconductor narratives.
- **Risk appetite:** constructive but still event-sensitive. Broad breadth and falling VIX support research activity, while the five-session decline immediately before today argues against treating one relief day as a regime change.

## 3. United States Market Map

- **Condition:** mixed and concentration-sensitive. On 24 July the S&P 500 rose **less than 0.1%**, the Dow gained **0.5%**, and Nasdaq fell **0.6%**; for the week they fell **0.6%**, **0.4%** and **2.1%**, respectively. [AP market close](https://apnews.com/article/stocks-dow-nasdaq-iran-oil-02d01b8f38ccd51f605c4414cdd4fa9b)
- **Leadership:** the Dow outperformed Nasdaq while oil and Treasury yields eased Friday; non-consensus financial infrastructure, healthcare throughput and recurring industrial services remain preferred over index-heavy AI concentration.
- **Macro drivers:** June CPI fell 0.4% month-on-month but remained 3.5% year-on-year; core CPI was 2.6% year-on-year. The 28–29 July FOMC meeting, oil/geopolitical volatility and Q2 earnings dominate near-term event risk. [Official BLS CPI](https://www.bls.gov/news.release/cpi.nr0.htm)
- **Strongest areas:** exchanges/clearing/data, custody/settlement/collateral, profitable software dislocations, healthcare throughput, mission systems, water/safety and workflow promotion.
- **Avoid/discount:** pre-revenue space/quantum, leveraged AI clouds, tenant-concentrated data-centre funding, managed care without claims proof and backlog treated as cash.
- **US-specific normalization:** diluted FCF/share after SBC, buybacks, insider events, customer/cloud concentration, AI-capex dependence, antitrust/platform risk and index/valuation concentration. Only Visa is a mega-cap among the US primary 15.

## 4. Full Matrix Segment Winners

### Scoring and evidence confidence

The requested weights are used exactly: Structural Node Position 10; Sovereignty 9; Early Capture And Promotion Geometry 11; Fundamental Quality 12; Cash Flow And Balance Sheet Quality 8; Valuation And Poker Pot Odds 10; Catalysts And Inflection 8; Price Strength And Entry Quality 7; Poker Weighted Expected Value 7; Mines Survival Probability 7; Economic Half Life 5; Clairefontaine Cohort Quality 4; Gamblers Fallacy Protection 2. **Total = 100.** Scores are comparative judgments anchored to current filings, dated price evidence and cohort-relative economics. Confidence is not upside probability. A `NO QUALIFIED WINNER TODAY` result is a valid finding, not missing data.

#### Auditable primary score vectors

Vector order: `SN/SV/PG/FQ/CB/VO/CI/EN/PE/MS/HL/CF/GF`.

| Ticker | SN/SV/PG/FQ/CB/VO/CI/EN/PE/MS/HL/CF/GF | Total |
|---|---|---|
| NSE:ICICIBANK | 9/9/8/12/8/8/7/4/6/6/5/4/2 | 88 |
| NSE:POWERGRID | 10/9/5/11/5/8/7/5/6/5/5/4/2 | 82 |
| NSE:SHRIRAMFIN | 8/8/8/10/7/8/7/5/6/5/5/3/2 | 82 |
| NSE:INDIAMART | 8/8/10/9/8/9/6/5/6/5/4/3/1 | 82 |
| NSE:MCX | 10/9/8/11/8/4/7/3/6/4/5/4/2 | 81 |
| NSE:BHARTIARTL | 9/8/7/11/6/5/7/5/6/5/5/4/2 | 80 |
| NSE:INDUSTOWER | 9/8/6/10/7/8/6/5/6/5/5/3/2 | 80 |
| NSE:PERSISTENT | 7/7/9/11/7/6/7/5/6/5/4/4/2 | 80 |
| NSE:OFSS | 8/8/8/10/8/6/6/3/6/5/5/4/2 | 79 |
| NSE:RELIANCE | 9/8/8/10/6/7/6/5/5/4/5/4/2 | 79 |
| NSE:LT | 8/8/7/11/6/6/8/4/5/4/5/4/2 | 78 |
| NSE:SUNPHARMA | 8/8/7/11/8/5/7/4/5/5/4/4/2 | 78 |
| NSE:WABAG | 7/6/10/10/7/6/7/4/5/4/5/4/2 | 77 |
| NSE:HDFCBANK | 9/9/6/8/8/10/5/3/5/4/5/3/2 | 77 |
| NSE:KFINTECH | 8/7/9/9/7/4/5/5/5/4/5/4/2 | 74 |
| NYSE:ICE | 10/9/7/12/8/8/7/4/7/6/5/4/2 | 89 |
| Nasdaq:CME | 10/9/6/12/8/8/7/4/7/7/5/4/2 | 89 |
| Nasdaq:ADBE | 9/8/8/12/8/10/6/4/7/5/5/3/2 | 87 |
| Nasdaq:TW | 9/8/8/11/8/7/8/5/7/5/5/4/2 | 87 |
| NYSE:UBER | 9/8/10/11/8/7/8/5/7/5/4/3/2 | 87 |
| NYSE:MCK | 9/8/7/11/8/9/7/5/7/6/5/3/2 | 87 |
| NYSE:BLK | 9/8/8/12/7/8/8/3/7/5/5/4/2 | 86 |
| NYSE:CACI | 8/8/9/11/7/9/8/5/7/5/4/3/2 | 86 |
| NYSE:BNY | 10/9/7/12/7/7/8/2/6/6/5/4/2 | 85 |
| NYSE:V | 10/9/5/12/8/6/6/5/7/6/5/4/2 | 85 |
| Nasdaq:CPRT | 9/9/6/11/8/8/6/4/6/6/5/4/2 | 84 |
| NYSE:TOST | 8/7/11/10/7/8/7/5/6/4/4/4/2 | 83 |
| NYSE:VLTO | 8/9/5/12/7/7/6/5/6/6/5/4/2 | 82 |
| NYSE:VEEV | 9/8/8/10/8/7/7/4/6/5/5/3/2 | 82 |
| NYSE:MSA | 8/8/6/12/7/7/6/5/6/6/5/4/2 | 82 |

### 4.1 Use-case winners

| Use Case | Best India | Best US | Best Overall | Runner-Up | MVP Score | Confidence | Why Winner | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| QC — Quality compounder | ICICI Bank (NSE:ICICIBANK) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | ICICI Bank (NSE:ICICIBANK) | 87 | 91 | Essential healthcare throughput plus expanding oncology/biopharma services and $5.4B FY26 FCF. | Customer and policy concentration. | STRUCTURAL COMPOUNDER |
| GR — Growth | Shriram Finance (NSE:SHRIRAMFIN) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | Tradeweb Markets (Nasdaq:TW) | 87 | 90 | Bookings, EBITDA and FCF are converting while ads, membership and AV distribution add independent paths. | Regulation, insurance costs and AV bypass. | HIGH-CONVICTION RESEARCH CANDIDATE |
| VA — Value | Shriram Finance (NSE:SHRIRAMFIN) | Adobe (Nasdaq:ADBE) | Adobe (Nasdaq:ADBE) | CACI International (NYSE:CACI) | 87 | 89 | Official FY26 guidance implies unusually low earnings pot odds despite substantial cash generation and real AI-first ARR; Shriram is the cleaner India value/growth blend after HDFC's margin breach. | AI displacement and management transition. | WAIT FOR CATALYST |
| IN — Income | Power Grid Corporation of India (NSE:POWERGRID) | CME Group (Nasdaq:CME) | CME Group (Nasdaq:CME) | Indus Towers (NSE:INDUSTOWER) | 89 | 94 | Benchmark liquidity, clearing and exceptional cash economics support distributions without requiring directional market calls. | ADV/capture normalization and rule changes. | STRUCTURAL COMPOUNDER |
| BC — Blue-chip core | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | 88 | 94 | Capital, underwriting, deposits and payments combine with better entry pot odds than the premium-priced US network. | Deposit and credit normalization. | STRUCTURAL COMPOUNDER |
| DF — Defensive | Sun Pharmaceutical Industries (NSE:SUNPHARMA) | Veralto (NYSE:VLTO) | Veralto (NYSE:VLTO) | McKesson (NYSE:MCK) | 82 | 88 | Regulated water/product-quality measurement has high recurring mix, low mine density and long installed-base life. | Organic softness, tariffs and acquisition execution. | STRUCTURAL COMPOUNDER |
| CY — Cyclical | Larsen & Toubro (NSE:LT) | NRG Energy (NYSE:NRG) | Larsen & Toubro (NSE:LT) | NRG Energy (NYSE:NRG) | 78 | 87 | Large diversified order book and improving working capital provide converted evidence across the capex cycle. | Project mix, geopolitics and cash conversion. | HIGH-CONVICTION RESEARCH CANDIDATE |
| MO — Momentum | NO QUALIFIED WINNER TODAY | BNY (NYSE:BNY) | BNY (NYSE:BNY) | NO QUALIFIED WINNER TODAY | 85 | 95 | Fresh Q2 fee growth, margin expansion and a result-day breakout are evidence-backed, but the gap weakens entry. | Gap failure, NII reversal and fee regulation. | WAIT FOR PULLBACK |
| EC — Early capture | VA Tech Wabag (NSE:WABAG) | Toast (NYSE:TOST) | Toast (NYSE:TOST) | Shriram Finance (NSE:SHRIRAMFIN) | 83 | 87 | Positive FCF and 20%+ operating growth support a real POS/payment Dealer-to-commerce-Table path; Wabag is the cleaner India Pawn-to-Rook path after KFin's margin breach. | Restaurant cycle, competition and dilution. | EARLY CAPTURE |
| TU — Turnaround | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | — | — | No screened issuer had both a damaged base and enough verified repair evidence to clear the hurdle. | Quota-filling would confuse price decline with operating repair. | NO QUALIFIED WINNER TODAY |
| SS — Special situation | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | — | — | No merger, demerger, restructuring or legal event had sufficiently verified odds and entry data. | Event timing and legal outcomes were not uniformly validated. | NO QUALIFIED WINNER TODAY |
| SR — Structural rail | Power Grid Corporation of India (NSE:POWERGRID) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | CME Group (Nasdaq:CME) | 89 | 90 | Four reinforcing rails—exchanges, clearing, data and mortgage workflow—create the broadest made House. | Debt, mortgage cyclicality and regulation. | STRUCTURAL COMPOUNDER |
| CI — Commodity / inflation | Himadri Speciality Chemical (NSE:HSCL) | NRG Energy (NYSE:NRG) | NRG Energy (NYSE:NRG) | Himadri Speciality Chemical (NSE:HSCL) | 78 | 87 | Generation, retail load and virtual-power-plant optionality offer several conversion paths beyond a pure commodity bet. | Leverage, ERCOT, hedging and regulation. | EARLY CAPTURE |
| SP — Speculative asymmetry | Kaynes Technology (NSE:KAYNES) | Rocket Lab (Nasdaq:RKLB) | Kaynes Technology (NSE:KAYNES) | Rocket Lab (Nasdaq:RKLB) | 68 | 80 | OSAT/critical-electronics promotion could materially change role and addressable market if customer qualification and utilization arrive. | Capex funding, qualification, utilization and negative post-capex FCF. | HIGH UPSIDE — HIGH MINE DENSITY |
| DS — Distressed | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | — | — | No impaired issuer offered adequate balance-sheet runway, governance evidence and positive weighted odds. | Distress can destroy optionality before recovery. | NO QUALIFIED WINNER TODAY |

### 4.2 GICS sector winners

| Sector | Best India | Best US | Best Overall | Primary Use Case | MVP Score | Confidence | Why Winner | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| Energy | Reliance Industries (NSE:RELIANCE) | Cheniere Energy (NYSE:LNG) | Reliance Industries (NSE:RELIANCE) | BC | 79 | 88 | Digital/retail mix provides non-commodity paths around the integrated-energy base. | Capex, O2C cycle and complexity. | WAIT FOR CATALYST |
| Materials | Himadri Speciality Chemical (NSE:HSCL) | Martin Marietta Materials (NYSE:MLM) | Martin Marietta Materials (NYSE:MLM) | CY | 76 | 82 | Aggregate reserves, local network density and infrastructure demand offer better made economics than early material qualification stories. | Construction cycle, pricing and input costs. | RESEARCH DEEPER |
| Industrials | Larsen & Toubro (NSE:LT) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | VA | 86 | 89 | Mission/cyber mix, backlog and FCF growth offer superior pot odds with embedded federal access. | Federal award timing and acquisition leverage. | HIGH-CONVICTION RESEARCH CANDIDATE |
| Consumer Discretionary | Mahindra & Mahindra (NSE:M&M) | O'Reilly Automotive (Nasdaq:ORLY) | O'Reilly Automotive (Nasdaq:ORLY) | QC | 80 | 86 | Aftermarket distribution density and non-discretionary repair demand create converted defensive retail economics. | Valuation, wage pressure and vehicle-cycle normalization. | HIGH-CONVICTION RESEARCH CANDIDATE |
| Consumer Staples | ITC (NSE:ITC) | PepsiCo (Nasdaq:PEP) | ITC (NSE:ITC) | IN | 76 | 89 | Cash generation, distribution and a discounted income/value setup offer better current pot odds than the US incumbent. | Tobacco regulation/tax, FMCG margin conversion and weak price trend. | RESEARCH DEEPER |
| Health Care | Sun Pharmaceutical Industries (NSE:SUNPHARMA) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | QC | 87 | 91 | Essential distribution plus services expansion converts demand into durable cash. | Customer and policy concentration. | STRUCTURAL COMPOUNDER |
| Financials | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Diversified clearing/data/workflow economics earn across multiple participant outcomes. | Regulation, leverage and mortgage cycle. | STRUCTURAL COMPOUNDER |
| Information Technology | Persistent Systems (NSE:PERSISTENT) | Adobe (Nasdaq:ADBE) | Adobe (Nasdaq:ADBE) | VA | 87 | 89 | Large converted cash flow and disruption-level valuation create better odds than high-multiple AI narratives. | AI substitution and ARR deceleration. | WAIT FOR CATALYST |
| Communication Services | Bharti Airtel (NSE:BHARTIARTL) | T-Mobile US (Nasdaq:TMUS) | T-Mobile US (Nasdaq:TMUS) | SR | 80 | 88 | Spectrum, billing, network density and direct customer access form a mature connectivity House. | Regulation, spectrum economics and leverage. | RESEARCH DEEPER |
| Utilities | Power Grid Corporation of India (NSE:POWERGRID) | NRG Energy (NYSE:NRG) | Power Grid Corporation of India (NSE:POWERGRID) | SR | 82 | 86 | Regulated transmission is paid across competing generation technologies. | Allowed-return changes and capex delays. | STRUCTURAL COMPOUNDER |
| Real Estate | DLF (NSE:DLF) | CBRE Group (NYSE:CBRE) | CBRE Group (NYSE:CBRE) | QC | 81 | 86 | Asset-light services and property workflows offer better cycle survival than levered property ownership. | Transaction cycle, rates and commercial-property stress. | HIGH-CONVICTION RESEARCH CANDIDATE |

Sector-gap evidence was separately checked so data abundance did not determine winners: [M&M FY26](https://www.mahindra.com/news-room/press-release/en/m-and-m-results-q4-f26-and-fy26), [ITC FY26](https://itcportal.com/media-centre/press-releases/media-statement-financial-results-for-the-quarter-and-year-ended-31st-march-2026.html), [DLF FY26](https://www.dlf.in/media-press-release/Q4FY26-Press-Release-DLF.pdf), [Cheniere Q1](https://lngir.cheniere.com/news-events/press-releases/detail/339/cheniere-reports-first-quarter-2026-results-and-raises-full), [Martin Marietta Q1](https://ir.martinmarietta.com/news-releases/news-release-details/martin-marietta-reports-first-quarter-2026-results), [O'Reilly Q1](https://corporate.oreillyauto.com/2026/04/29/oreilly-automotive-inc-reports-first-quarter-2026-results/), [PepsiCo Q2](https://investors.pepsico.com/docs/pepsico-5v9wci20/media/Files/investors/q2-2026-earnings-release.pdf), [T-Mobile Q1](https://www.t-mobile.com/news/business/t-mobile-q1-2026-earnings), and [CBRE Q1](https://ir.cbre.com/press-releases/detail/265/cbre-group-inc-reports-financial-results-for-q1-2026). DLF remains valuation-caution; sector nomination does not make it a top-30 primary candidate.

### 4.3 Market-cap winners

| Market Cap | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Liquidity Check | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| MEGA | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | ICICI Bank (NSE:ICICIBANK) | QC | 88 | 94 | Pass—deep institutional liquidity; executable quote still requires revalidation. | Deposit/NIM and credit cycle. | STRUCTURAL COMPOUNDER |
| LARGE | Power Grid Corporation of India (NSE:POWERGRID) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Pass—NYSE large-cap liquidity; no live order book used. | Regulation, mortgage cycle and debt. | STRUCTURAL COMPOUNDER |
| MID | IndiaMART InterMESH (NSE:INDIAMART) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | VA | 86 | 89 | Pass for research; validate spread and volume before execution. | Federal timing and ARKA leverage. | HIGH-CONVICTION RESEARCH CANDIDATE |
| SMALL | VA Tech Wabag (NSE:WABAG) | NO QUALIFIED WINNER TODAY | VA Tech Wabag (NSE:WABAG) | EC | 77 | 86 | Conditional—liquidity and current promoter/pledge checks required. | Receivables, overseas execution and liquidity. | EARLY CAPTURE |
| MICRO | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | — | — | — | Fail | Spread, manipulation, governance and data gaps. | NO QUALIFIED WINNER TODAY |
| NANO | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | — | — | — | Fail | Extreme liquidity and information asymmetry. | NO QUALIFIED WINNER TODAY |

### 4.4 Maturity-stage winners

| Maturity Stage | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Why Winner | Main Mine | Action |
|---|---|---|---|---|---|---|---|---|---|
| M1 — Pre-commercial / emerging | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | SP | — | — | ASTS and IonQ remain pre-conversion with valuation and financing ahead of commercial proof. | Funding/dilution before recurring commercial evidence | NO QUALIFIED WINNER TODAY |
| M2 — Early growth / pre-profit | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | SP | — | — | Rocket Lab and Tempus remain research options, not qualified winners at current pot odds. | Cash runway and per-share dilution | NO QUALIFIED WINNER TODAY |
| M3 — Scaling growth | Newgen Software Technologies (NSE:NEWGEN) | Samsara (NYSE:IOT) | Samsara (NYSE:IOT) | EC | 76 | 88 | Connected-operations data has measurable ARR/product-attach milestones and positive promotion geometry. | SBC and emerging-product conversion | EARLY CAPTURE |
| M4 — Profitable growth | Shriram Finance (NSE:SHRIRAMFIN) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | GR | 87 | 90 | Profitable marketplace growth now converts into meaningful FCF. | Regulatory and insurance-cost correlation | HIGH-CONVICTION RESEARCH CANDIDATE |
| M5 — Mature compounder | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Multiple reinforcing infrastructure rails and strong cash economics. | Rule/capture-rate change | STRUCTURAL COMPOUNDER |
| M6 — Cash-generating incumbent | Power Grid Corporation of India (NSE:POWERGRID) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | QC | 87 | 91 | Essential throughput and services expansion support recurring cash generation. | Customer concentration | STRUCTURAL COMPOUNDER |
| M7 — Declining / disrupted / turnaround | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | TU | — | — | No damaged incumbent showed enough verified repair to overcome cohort alternatives. | Unproven repair | NO QUALIFIED WINNER TODAY |

### 4.5 Volatility winners

| Volatility Class | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Why It Fits | Risk Control | Action |
|---|---|---|---|---|---|---|---|---|---|
| LV — Low volatility | Power Grid Corporation of India (NSE:POWERGRID) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | QC | 87 | 91 | Essential healthcare flow and made FCF with lower market sensitivity. | Monitor customer mix and policy; revalidate price. | STRUCTURAL COMPOUNDER |
| NV — Normal volatility | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Best blend of structural control, evidence and valuation in the normal-volatility cohort. | Stage entry around Q2 evidence; monitor leverage. | STRUCTURAL COMPOUNDER |
| HV — High volatility | Shriram Finance (NSE:SHRIRAMFIN) | Adobe (Nasdaq:ADBE) | Adobe (Nasdaq:ADBE) | VA | 87 | 89 | Large cash generation and low implied expectations compensate for volatility better than pre-profit peers. | Require ARR/retention evidence; avoid catalyst-size exposure. | WAIT FOR CATALYST |

### 4.6 Risk-sensitivity winners

| Risk Tag | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Why Exposure Is Attractive | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| BETA | Larsen & Toubro (NSE:LT) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | GR | 87 | 90 | Cash-generating platform leverage rather than pre-profit beta. | Macro slowdown and regulation. | HIGH-CONVICTION RESEARCH CANDIDATE |
| LIQ | VA Tech Wabag (NSE:WABAG) | NO QUALIFIED WINNER TODAY | VA Tech Wabag (NSE:WABAG) | EC | 77 | 86 | Potential small-cap rerating after order-to-cash proof. | Spread, ownership validation and receivables. | EARLY CAPTURE |
| EVT | Reliance Industries (NSE:RELIANCE) | CME Group (Nasdaq:CME) | CME Group (Nasdaq:CME) | IN | 89 | 94 | Released operating evidence rather than an unpriced binary event. | ADV/capture normalization and event-gap reversal. | STRUCTURAL COMPOUNDER |
| CMD | Himadri Speciality Chemical (NSE:HSCL) | NRG Energy (NYSE:NRG) | NRG Energy (NYSE:NRG) | CI | 78 | 87 | Several paths beyond spot commodity direction. | ERCOT, hedge book and leverage. | EARLY CAPTURE |
| RATE | ICICI Bank (NSE:ICICIBANK) | BNY (NYSE:BNY) | ICICI Bank (NSE:ICICIBANK) | QC | 88 | 94 | Rate exposure buffered by capital, fees and customer ownership. | Deposit competition and NIM compression. | STRUCTURAL COMPOUNDER |
| REG | Power Grid Corporation of India (NSE:POWERGRID) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Permissioned market infrastructure with diversified revenue. | Adverse rule economics or compliance/cyber failure. | STRUCTURAL COMPOUNDER |
| GEO | Larsen & Toubro (NSE:LT) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | VA | 86 | 89 | Embedded access and differentiated systems, not only a defence label. | Federal timing, budget priorities and leverage. | HIGH-CONVICTION RESEARCH CANDIDATE |

### 4.7 Structural-role winners

| Casino Role | Best India | Best US | Best Overall | Sector | MVP Score | Confidence | Why Winner | Valuation Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| PLAYER | Shriram Finance (NSE:SHRIRAMFIN) | NRG Energy (NYSE:NRG) | Shriram Finance (NSE:SHRIRAMFIN) | Financials | 82 | 88 | The lending Player has better current valuation and converted profit growth than high-mine operating Players. | Moderate; credit-cycle discount is warranted. | HIGH-CONVICTION RESEARCH CANDIDATE |
| DEALER | Bharti Airtel (NSE:BHARTIARTL) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | Health Care | 87 | 91 | Essential healthcare distribution earns repeatedly and is adding higher-margin services; Airtel is the stronger India Dealer after KFin's margin breach. | Low/moderate versus converted FCF. | STRUCTURAL COMPOUNDER |
| TABLE | IndiaMART InterMESH (NSE:INDIAMART) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | Industrials | 87 | 90 | Marketplace liquidity now converts into cash while ads, membership and AV distribution widen capture. | Moderate; growth must remain mid-teens or better. | HIGH-CONVICTION RESEARCH CANDIDATE |
| HOUSE | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | Financials | 89 | 90 | Rules, access, clearing, data and workflows form the strongest multi-rail House. | Moderate; non-heroic but Q2 must confirm. | STRUCTURAL COMPOUNDER |
| CHIP | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | Visa (NYSE:V) | Financials | 85 | 92 | Global authorization and settlement collect across commerce with exceptional margins and ubiquity. | High near the annual high. | WAIT FOR PULLBACK |

### 4.8 Chess-promotion winners

| Chess Segment | Best India | Best US | Best Overall | Promotion Probability | Time Horizon | Main Milestone | Main Mine | Action |
|---|---|---|---|---|---|---|---|---|
| Best current PAWN | Newgen Software Technologies (NSE:NEWGEN) | Itron (Nasdaq:ITRI) | Itron (Nasdaq:ITRI) | 55% | 3–5 years | Outcomes growth, backlog stabilization and repeatable FCF | Utility deployment timing | EARLY CAPTURE |
| Best current KNIGHT | HDB Financial Services (NSE:HDBFS) | Kinsale Capital (NYSE:KNSL) | Kinsale Capital (NYSE:KNSL) | 55% | 3–5 years | Sustain underwriting discipline through softer pricing | Reserve/catastrophe correlation | WATCHLIST |
| Best current BISHOP | IndiaMART InterMESH (NSE:INDIAMART) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | 60% | 3–5 years | Mission mix and FCF/share compound | Award timing | HIGH-CONVICTION RESEARCH CANDIDATE |
| Best current ROOK | Power Grid Corporation of India (NSE:POWERGRID) | Tradeweb Markets (Nasdaq:TW) | Tradeweb Markets (Nasdaq:TW) | 70% | 3–5 years | Multi-asset share and organic revenue | Capture-rate compression | STRUCTURAL COMPOUNDER |
| Best current QUEEN | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | 80% deeper House | 3–5 years | Data growth and deleveraging | Regulatory economics | STRUCTURAL COMPOUNDER |
| Best PAWN → KNIGHT | PB Fintech (NSE:PBFINTECH) | Hims & Hers Health (NYSE:HIMS) | PB Fintech (NSE:PBFINTECH) | 45% | 3–5 years | Recurring profit and per-share FCF | Regulatory/customer-acquisition economics | HIGH UPSIDE — HIGH MINE DENSITY |
| Best PAWN → BISHOP | Himadri Speciality Chemical (NSE:HSCL) | Tempus AI (Nasdaq:TEM) | Himadri Speciality Chemical (NSE:HSCL) | 50% | 3–5 years | Qualified customers and post-capex FCF | Technology qualification | HIGH UPSIDE — HIGH MINE DENSITY |
| Best PAWN → ROOK | VA Tech Wabag (NSE:WABAG) | Samsara (NYSE:IOT) | VA Tech Wabag (NSE:WABAG) | 60% | 3–5 years | Framework conversion, collections and O&M mix | Working-capital recurrence | EARLY CAPTURE |
| Best PAWN → QUEEN | Eternal (NSE:ETERNAL) | Toast (NYSE:TOST) | Toast (NYSE:TOST) | 70% | 2–4 years | Recurring gross profit and per-share FCF | Dilution | EARLY CAPTURE |

### 4.9 Food-chain winners

| Food Chain Role | Best India | Best US | Best Overall | Capture Mechanism | MVP Score | Confidence | Why Winner | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| PRODUCER | Reliance Industries (NSE:RELIANCE) | Veralto (NYSE:VLTO) | Reliance Industries (NSE:RELIANCE) | Integrated production plus downstream distribution/platform ownership. | 79 | 88 | Produces energy while controlling increasingly valuable digital and retail distribution layers. | Capex and conglomerate complexity. | WAIT FOR CATALYST |
| PRIMARY CONSUMER | NO QUALIFIED WINNER TODAY | NRG Energy (NYSE:NRG) | NRG Energy (NYSE:NRG) | Generation-to-retail load plus VPP orchestration. | 78 | 87 | Consumes fuel/capacity inputs but adds retail load and orchestration rather than relying only on generation spreads. | Commodity, hedge and leverage correlation. | EARLY CAPTURE |
| SECONDARY CONSUMER | Larsen & Toubro (NSE:LT) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | Embedded mission access and differentiated system delivery. | 86 | 89 | Converts labor, technology and acquired IP into embedded mission systems with backlog and FCF evidence. | Federal timing and leverage. | HIGH-CONVICTION RESEARCH CANDIDATE |
| TERTIARY CONSUMER | IndiaMART InterMESH (NSE:INDIAMART) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | Marketplace liquidity, memberships, ads and AV distribution. | 87 | 90 | Owns customer discovery/liquidity and collects across local commerce participants. | Regulation, insurance and bypass. | HIGH-CONVICTION RESEARCH CANDIDATE |
| QUATERNARY CONSUMER | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | Tolls on access, risk transfer, clearing, data and workflow. | 89 | 90 | Controls permission, matching, clearing, data and workflow at the top of the economic chain. | Regulation and operational/cyber concentration. | STRUCTURAL COMPOUNDER |

### 4.10 Economic half-life winners

| Half-Life Class | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Durability Logic | Main Decay Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| ULTRA-SHORT | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | SP | — | — | No durable cash half-life | Attention decay | NO QUALIFIED WINNER TODAY |
| SHORT | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | NO QUALIFIED WINNER TODAY | SP | — | — | Milestone-dependent rather than recurring | Capital-market access | NO QUALIFIED WINNER TODAY |
| MEDIUM | Larsen & Toubro (NSE:LT) | NRG Energy (NYSE:NRG) | Larsen & Toubro (NSE:LT) | CY | 78 | 87 | National capex cycle plus order backlog | Order quality/working capital | HIGH-CONVICTION RESEARCH CANDIDATE |
| LONG | VA Tech Wabag (NSE:WABAG) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | GR | 87 | 90 | Recurring multi-sided marketplace behavior | Disintermediation | HIGH-CONVICTION RESEARCH CANDIDATE |
| VERY LONG | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Permissioned infrastructure and self-reinforcing liquidity | Regulatory economics or technology migration | STRUCTURAL COMPOUNDER |

### Canonical classification registry — all named research candidates

Every stock named as a primary, additional, early-capture, high-mine, valuation-caution or sector-gap candidate has one primary use case, zero-to-three secondary use cases and the required vector. `COM` was confirmed as the listed common/equity class for this screen.

#### Primary 30

```text
NSE:ICICIBANK | India | NSE | Financials > Banks > Banks > Diversified Banks | QC | BC, SR | MEGA | M5 | COM | NV | RATE, REG, BETA
NSE:POWERGRID | India | NSE | Utilities > Utilities > Electric Utilities > Electric Transmission | SR | IN, DF | LARGE | M6 | COM | LV | RATE, REG
NSE:SHRIRAMFIN | India | NSE | Financials > Financial Services > Consumer Finance > Diversified Finance | GR | VA, EC | LARGE | M4 | COM | HV | RATE, BETA, LIQ
NSE:INDIAMART | India | NSE | Communication Services > Media & Entertainment > Interactive Media & Services > B2B Marketplace | EC | QC, SR | MID | M4 | COM | HV | BETA, REG
NSE:MCX | India | NSE | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | SR | QC, MO | MID | M5 | COM | HV | REG, EVT, CMD
NSE:BHARTIARTL | India | NSE | Communication Services > Telecommunication Services > Diversified Telecom > Wireless Services | BC | SR, QC | MEGA | M5 | COM | NV | REG, GEO, BETA
NSE:INDUSTOWER | India | NSE | Communication Services > Telecommunication Services > Diversified Telecom > Telecom Infrastructure | IN | SR, VA | LARGE | M6 | COM | NV | REG, LIQ, BETA
NSE:PERSISTENT | India | NSE | Information Technology > Software & Services > IT Services > IT Consulting & Digital Engineering | GR | QC, MO | MID | M4 | COM | HV | BETA, EVT, GEO
NSE:OFSS | India | NSE | Information Technology > Software & Services > Software > Application Software | VA | QC, SR | LARGE | M5 | COM | NV | LIQ, EVT, REG
NSE:RELIANCE | India | NSE | Energy > Energy > Oil, Gas & Consumable Fuels > Integrated Oil & Gas | BC | SR, VA | MEGA | M6 | COM | NV | CMD, GEO, REG
NSE:LT | India | NSE | Industrials > Capital Goods > Construction & Engineering > Construction & Engineering | CY | QC, SR | MEGA | M5 | COM | NV | BETA, GEO, CMD
NSE:SUNPHARMA | India | NSE | Health Care > Pharmaceuticals, Biotechnology & Life Sciences > Pharmaceuticals > Pharmaceuticals | DF | QC, GR | LARGE | M5 | COM | LV | REG, GEO, EVT
NSE:WABAG | India | NSE | Industrials > Commercial & Professional Services > Commercial Services & Supplies > Environmental Services | EC | SR, GR | SMALL | M4 | COM | HV | LIQ, GEO, EVT
NSE:HDFCBANK | India | NSE | Financials > Banks > Banks > Diversified Banks | VA | QC, BC | MEGA | M5 | COM | LV | RATE, REG, EVT
NSE:KFINTECH | India | NSE | Financials > Financial Services > Capital Markets > Asset-Servicing Technology | EC | SR, GR | MID | M4 | COM | NV | REG, EVT, LIQ
NYSE:ICE | United States | NYSE | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | SR | QC, BC | LARGE | M5 | COM | NV | REG, RATE, EVT
Nasdaq:CME | United States | Nasdaq | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | IN | SR, QC | LARGE | M5 | COM | LV | REG, RATE, EVT
Nasdaq:ADBE | United States | Nasdaq | Information Technology > Software & Services > Software > Application Software | VA | QC, GR | LARGE | M5 | COM | HV | BETA, EVT, REG
Nasdaq:TW | United States | Nasdaq | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | GR | SR, QC | LARGE | M4 | COM | NV | REG, RATE, EVT
NYSE:UBER | United States | NYSE | Industrials > Transportation > Ground Transportation > Passenger Ground Transportation | GR | EC, SR | LARGE | M4 | COM | HV | BETA, REG, EVT
NYSE:MCK | United States | NYSE | Health Care > Health Care Equipment & Services > Health Care Providers & Services > Health Care Distributors | QC | DF, SR | LARGE | M6 | COM | LV | REG, EVT
NYSE:BLK | United States | NYSE | Financials > Financial Services > Capital Markets > Asset Management & Custody Banks | BC | QC, SR | LARGE | M5 | COM | NV | BETA, RATE, REG
NYSE:CACI | United States | NYSE | Industrials > Commercial & Professional Services > Professional Services > Research & Consulting Services | VA | GR, SR | MID | M4 | COM | NV | GEO, REG, EVT
NYSE:BNY | United States | NYSE | Financials > Financial Services > Capital Markets > Asset Management & Custody Banks | DF | SR, QC | LARGE | M6 | COM | LV | RATE, REG, EVT
NYSE:V | United States | NYSE | Financials > Financial Services > Financial Services > Transaction & Payment Processing Services | BC | SR, QC | MEGA | M5 | COM | LV | REG, GEO, EVT
Nasdaq:CPRT | United States | Nasdaq | Industrials > Commercial & Professional Services > Commercial Services & Supplies > Diversified Support Services | QC | SR, VA | LARGE | M5 | COM | NV | EVT, BETA
NYSE:TOST | United States | NYSE | Financials > Financial Services > Financial Services > Transaction & Payment Processing Services | EC | GR, SR | LARGE | M4 | COM | HV | BETA, REG, LIQ
NYSE:VLTO | United States | NYSE | Industrials > Capital Goods > Machinery > Industrial Machinery & Supplies | DF | QC, SR | LARGE | M5 | COM | LV | REG, BETA
NYSE:VEEV | United States | NYSE | Health Care > Health Care Equipment & Services > Health Care Technology > Health Care Technology | GR | QC, EC | LARGE | M4 | COM | NV | REG, EVT, BETA
NYSE:MSA | United States | NYSE | Industrials > Capital Goods > Machinery > Industrial Machinery & Supplies | QC | DF, SR | MID | M5 | COM | LV | REG, BETA, EVT
```

#### Extended and sector-gap registry

```text
NSE:HDBFS | India | NSE | Financials > Financial Services > Consumer Finance > Diversified Finance | EC | GR, VA | MID | M4 | COM | HV | RATE, LIQ, EVT
NSE:HDFCAMC | India | NSE | Financials > Financial Services > Capital Markets > Asset Management & Custody Banks | QC | SR, GR | LARGE | M5 | COM | NV | REG, BETA, EVT
NSE:HDFCLIFE | India | NSE | Financials > Insurance > Life & Health Insurance > Life & Health Insurance | GR | DF, SR | LARGE | M4 | COM | NV | REG, RATE, EVT
NSE:HSCL | India | NSE | Materials > Materials > Chemicals > Specialty Chemicals | CI | EC, GR | MID | M4 | COM | HV | CMD, LIQ, EVT
NSE:GRAVITA | India | NSE | Materials > Materials > Metals & Mining > Diversified Metals & Mining | EC | CI, GR | SMALL | M4 | COM | HV | CMD, GEO, LIQ
NSE:ANGELONE | India | NSE | Financials > Financial Services > Capital Markets > Investment Banking & Brokerage | MO | EC, SP | MID | M4 | COM | HV | REG, BETA, LIQ
NSE:ADANIPORTS | India | NSE | Industrials > Transportation > Transportation Infrastructure > Marine Ports & Services | SR | QC, GR | LARGE | M5 | COM | NV | GEO, REG, EVT
NSE:CAMS | India | NSE | Financials > Financial Services > Capital Markets > Asset-Servicing Technology | SR | QC, IN | MID | M5 | COM | NV | REG, EVT
NSE:CDSL | India | NSE | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | SR | QC, MO | MID | M5 | COM | HV | REG, BETA, EVT
NSE:NEWGEN | India | NSE | Information Technology > Software & Services > Software > Application Software | EC | GR, SR | SMALL | M3 | COM | HV | LIQ, EVT, BETA
NSE:SAGILITY | India | NSE | Health Care > Health Care Equipment & Services > Health Care Services > Health Care Support Services | EC | GR | MID | M3 | COM | HV | GEO, LIQ, EVT
NSE:POLYCAB | India | NSE | Industrials > Capital Goods > Electrical Equipment > Electrical Components & Equipment | QC | GR, SR | LARGE | M4 | COM | HV | CMD, BETA, EVT
NSE:PBFINTECH | India | NSE | Financials > Financial Services > Financial Services > Insurance Marketplace | SP | EC, GR | LARGE | M3 | COM | HV | REG, BETA, LIQ
NSE:SOLARINDS | India | NSE | Materials > Materials > Chemicals > Diversified Chemicals | GR | CI, SP | LARGE | M4 | COM | HV | GEO, REG, EVT
NSE:KAYNES | India | NSE | Information Technology > Technology Hardware & Equipment > Electronic Equipment > Electronic Manufacturing Services | SP | EC, GR | MID | M3 | COM | HV | LIQ, EVT, GEO
NSE:ETERNAL | India | NSE | Consumer Discretionary > Consumer Services > Hotels, Restaurants & Leisure > Restaurants & Delivery | SP | GR, EC | LARGE | M3 | COM | HV | BETA, LIQ, REG
NSE:KPITTECH | India | NSE | Information Technology > Software & Services > IT Services > Automotive Technology Services | GR | EC | MID | M4 | COM | HV | BETA, EVT, GEO
NSE:NETWEB | India | NSE | Information Technology > Technology Hardware & Equipment > Technology Hardware > Servers & Computing Systems | SP | GR, EC | SMALL | M3 | COM | HV | LIQ, BETA, EVT
NSE:AMBER | India | NSE | Consumer Discretionary > Consumer Durables & Apparel > Household Durables > Consumer Electronics | SP | GR, EC | MID | M3 | COM | HV | CMD, LIQ, EVT
NYSE:KNSL | United States | NYSE | Financials > Insurance > Insurance > Property & Casualty Insurance | QC | GR, DF | MID | M4 | COM | HV | EVT, REG, BETA
Nasdaq:CTAS | United States | Nasdaq | Industrials > Commercial & Professional Services > Commercial Services & Supplies > Diversified Support Services | QC | DF, IN | LARGE | M5 | COM | LV | BETA, EVT
NYSE:HUBB | United States | NYSE | Industrials > Capital Goods > Electrical Equipment > Electrical Components & Equipment | GR | SR, QC | MID | M5 | COM | NV | BETA, CMD, EVT
NYSE:GWRE | United States | NYSE | Information Technology > Software & Services > Software > Application Software | EC | GR, SR | MID | M3 | COM | HV | BETA, EVT, LIQ
NYSE:SPGI | United States | NYSE | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | SR | QC, BC | LARGE | M5 | COM | LV | REG, RATE, EVT
NYSE:NRG | United States | NYSE | Utilities > Utilities > Independent Power & Renewable Electricity Producers > Independent Power Producers | CI | CY, EC | LARGE | M4 | COM | HV | CMD, RATE, REG
Nasdaq:VRSK | United States | Nasdaq | Industrials > Commercial & Professional Services > Professional Services > Research & Consulting Services | QC | SR, DF | LARGE | M5 | COM | LV | REG, EVT
NYSE:BR | United States | NYSE | Industrials > Commercial & Professional Services > Professional Services > Data Processing & Outsourced Services | SR | QC, IN | LARGE | M5 | COM | LV | REG, EVT, RATE
Nasdaq:ITRI | United States | Nasdaq | Information Technology > Technology Hardware & Equipment > Electronic Equipment > Electronic Equipment & Instruments | EC | SR, GR | MID | M3 | COM | HV | EVT, REG, BETA
NYSE:CNM | United States | NYSE | Industrials > Capital Goods > Trading Companies & Distributors > Trading Companies & Distributors | CY | SR, VA | MID | M4 | COM | NV | RATE, BETA, LIQ
NYSE:IOT | United States | NYSE | Information Technology > Software & Services > Software > Systems Software | EC | GR, SR | LARGE | M3 | COM | HV | BETA, LIQ, EVT
NYSE:PCOR | United States | NYSE | Information Technology > Software & Services > Software > Application Software | EC | GR, SR | MID | M3 | COM | HV | RATE, BETA, LIQ
Nasdaq:ALKT | United States | Nasdaq | Information Technology > Software & Services > Software > Application Software | EC | GR, SR | MID | M3 | COM | HV | RATE, LIQ, EVT
NYSE:HIMS | United States | NYSE | Health Care > Health Care Equipment & Services > Health Care Providers & Services > Health Care Services | SP | GR, EC | LARGE | M3 | COM | HV | REG, LIQ, EVT
Nasdaq:PLTR | United States | Nasdaq | Information Technology > Software & Services > Software > Systems Software | QC | GR, SR | MEGA | M4 | COM | HV | GEO, REG, BETA
Nasdaq:HOOD | United States | Nasdaq | Financials > Financial Services > Capital Markets > Investment Banking & Brokerage | SP | MO, EC | LARGE | M4 | COM | HV | REG, BETA, LIQ
Nasdaq:RKLB | United States | Nasdaq | Industrials > Capital Goods > Aerospace & Defense > Aerospace & Defense | SP | EC, GR | LARGE | M2 | COM | HV | EVT, LIQ, GEO
Nasdaq:TEM | United States | Nasdaq | Health Care > Health Care Equipment & Services > Health Care Technology > Health Care Technology | SP | EC, GR | MID | M2 | COM | HV | REG, LIQ, EVT
Nasdaq:APLD | United States | Nasdaq | Information Technology > Software & Services > IT Services > Internet Services & Infrastructure | SP | EC, CY | MID | M2 | COM | HV | RATE, LIQ, EVT
Nasdaq:CRWV | United States | Nasdaq | Information Technology > Software & Services > IT Services > Internet Services & Infrastructure | SP | GR, EC | LARGE | M3 | COM | HV | RATE, LIQ, EVT
Nasdaq:ASTS | United States | Nasdaq | Communication Services > Telecommunication Services > Wireless Telecommunication Services > Satellite Communications | SP | EC, GR | LARGE | M1 | COM | HV | EVT, LIQ, GEO
NYSE:IONQ | United States | NYSE | Information Technology > Technology Hardware & Equipment > Technology Hardware > Quantum Computing Systems | SP | EC, GR | MID | M1 | COM | HV | LIQ, EVT, BETA
NYSE:LNG | United States | NYSE | Energy > Energy > Oil, Gas & Consumable Fuels > Oil & Gas Storage & Transportation | IN | CI, SR | LARGE | M6 | COM | NV | CMD, GEO, REG
NYSE:MLM | United States | NYSE | Materials > Materials > Construction Materials > Construction Materials | CY | QC, CI | LARGE | M5 | COM | NV | CMD, RATE, BETA
Nasdaq:ORLY | United States | Nasdaq | Consumer Discretionary > Consumer Discretionary Distribution & Retail > Specialty Retail > Automotive Retail | QC | DF, BC | LARGE | M5 | COM | LV | BETA, EVT
Nasdaq:PEP | United States | Nasdaq | Consumer Staples > Food, Beverage & Tobacco > Beverages > Soft Drinks & Non-alcoholic Beverages | DF | IN, BC | MEGA | M6 | COM | LV | CMD, GEO, REG
Nasdaq:TMUS | United States | Nasdaq | Communication Services > Telecommunication Services > Wireless Telecommunication Services > Wireless Telecommunication Services | SR | QC, BC | MEGA | M5 | COM | LV | REG, RATE, EVT
NYSE:CBRE | United States | NYSE | Real Estate > Real Estate Management & Development > Real Estate Management & Development > Real Estate Services | QC | SR, CY | LARGE | M5 | COM | NV | RATE, BETA, EVT
NSE:M&M | India | NSE | Consumer Discretionary > Automobiles & Components > Automobiles > Automobile Manufacturers | CY | QC, VA | LARGE | M5 | COM | NV | BETA, CMD, RATE
NSE:ITC | India | NSE | Consumer Staples > Food, Beverage & Tobacco > Tobacco > Tobacco | IN | VA, DF | LARGE | M6 | COM | LV | REG, CMD
NSE:DLF | India | NSE | Real Estate > Real Estate Management & Development > Real Estate Management & Development > Real Estate Development | CY | IN, QC | LARGE | M5 | COM | HV | RATE, REG, BETA
```

### Cross-framework audit of the primary 30

| Candidate | Poker | Casino | Food Chain | Half-Life | Chess | Promotion | Clairefontaine | Sovereignty | Mine Density | Fallacy Filter |
|---|---|---|---|---|---|---|---|---|---|---|
| NSE:ICICIBANK | FULL HOUSE | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 75% | Level 7 | 9/10 | LOW | STRUCTURAL PATTERN; analogy not used |
| NSE:POWERGRID | FULL HOUSE | HOUSE | QUATERNARY CONSUMER | VERY LONG | ROOK → ROOK | 80% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:SHRIRAMFIN | FULL HOUSE | PLAYER | SECONDARY CONSUMER | LONG | ROOK → QUEEN | 65% | Level 6 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:INDIAMART | STRAIGHT | TABLE | TERTIARY CONSUMER | LONG | BISHOP → QUEEN | 60% | Level 5 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:MCX | OVERPLAYED HAND | HOUSE | QUATERNARY CONSUMER | VERY LONG | ROOK → QUEEN | 55% | Level 7 | 9/10 | HIGH | STRUCTURAL PATTERN; analogy not used |
| NSE:BHARTIARTL | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:INDUSTOWER | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | ROOK → ROOK | 60% | Level 6 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:PERSISTENT | FULL HOUSE | DEALER | SECONDARY CONSUMER | LONG | BISHOP → ROOK | 55% | Level 6 | 7/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:OFSS | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | BISHOP → ROOK | 55% | Level 6 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:RELIANCE | FULL HOUSE | TABLE | PRODUCER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:LT | FULL HOUSE | DEALER | SECONDARY CONSUMER | LONG | ROOK → QUEEN | 55% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:SUNPHARMA | FULL HOUSE | PLAYER | PRODUCER | LONG | BISHOP → ROOK | 55% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:WABAG | STRAIGHT | PLAYER | SECONDARY CONSUMER | LONG | BISHOP → ROOK | 60% | Level 5 | 6/10 | HIGH | STRUCTURAL PATTERN; analogy not used |
| NSE:HDFCBANK | DRAW | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 70% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:KFINTECH | DRAW | DEALER | TERTIARY CONSUMER | VERY LONG | BISHOP → ROOK | 70% | Level 6 | 7/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NYSE:ICE | STRAIGHT FLUSH | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 80% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| Nasdaq:CME | STRAIGHT FLUSH | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 80% | Level 7 | 9/10 | LOW | STRUCTURAL PATTERN; analogy not used |
| Nasdaq:ADBE | FULL HOUSE | TABLE | TERTIARY CONSUMER | LONG | ROOK → QUEEN | 60% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| Nasdaq:TW | FULL HOUSE | TABLE | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 70% | Level 7 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NYSE:UBER | FULL HOUSE | TABLE | TERTIARY CONSUMER | LONG | ROOK → QUEEN | 65% | Level 6 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NYSE:MCK | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NYSE:BLK | FULL HOUSE | TABLE | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NYSE:CACI | FULL HOUSE | DEALER | SECONDARY CONSUMER | LONG | BISHOP → ROOK | 60% | Level 6 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NYSE:BNY | STRAIGHT FLUSH | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 75% | Level 7 | 9/10 | LOW | STRUCTURAL PATTERN; analogy not used |
| NYSE:V | STRAIGHT FLUSH | CHIP | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 80% | Level 8 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| Nasdaq:CPRT | FULL HOUSE | HOUSE | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NYSE:TOST | STRAIGHT | CHIP | TERTIARY CONSUMER | LONG | BISHOP → QUEEN | 70% | Level 6 | 7/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NYSE:VLTO | FULL HOUSE | DEALER | PRODUCER | LONG | ROOK → ROOK | 70% | Level 7 | 9/10 | LOW | STRUCTURAL PATTERN; analogy not used |
| NYSE:VEEV | FULL HOUSE | TABLE | TERTIARY CONSUMER | LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NYSE:MSA | FULL HOUSE | DEALER | PRODUCER | LONG | BISHOP → ROOK | 55% | Level 7 | 8/10 | LOW | STRUCTURAL PATTERN; analogy not used |

`Promotion probability` is conditional business-role migration—not a price-target probability. Mine density combines funding, debt, dilution, regulation, governance, concentration, technology, commodity, currency, rate, execution, valuation and liquidity correlations.

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

### 27 July evidence delta — supersedes stale gates in the 16 July thesis notes

- **ICICI Bank — gate passed / score 88:** Q1 PAT grew 15.9%, core operating profit 15.6%, fee income 23.5%, deposits 14.0% and loans 19.6%; NIM was 4.36%, net NPA 0.35% and CET1 16.19%. The faster loan growth makes funding the next mine, but the made hand strengthened. [Official Q1 review](https://www.icici.bank.in/about-us/news-room/2026/performance-review-quarter-ended-june-30-2026)
- **HDFC Bank — prior invalidation triggered / score 77:** Q1 standalone PAT grew about 5% and NII about 7%, but NIM fell to a record-low 3.26%, below this screen's prior 3.3% invalidation threshold; gross/net NPA were 1.17%/0.41%. Action is `THESIS WEAKENING` until a margin floor is evidenced. [Official result archive](https://www.hdfc.bank.in/about-us/investor-relations/financial-results), [result summary](https://www.business-standard.com/companies/quarterly-results/hdfc-bank-q1fy27-results-net-profit-rises-5-to-19-060-cr-nii-grows-7-126071800598_1.html)
- **KFin Technologies — prior invalidation triggered / score 74:** Q1 revenue from operations was ₹3,565.4M versus ₹2,740.6M, but EBITDA margin fell to 34.2% from 41.5% and PBT slipped to ₹1,036.6M from ₹1,051.6M. The price rose 10.67% on 27 July, worsening entry while acquisition-separated conversion remains unresolved. Action is `THESIS WEAKENING`. [Official Q1 KPI](https://investor.kfintech.com/quarterly-key-performance-indicators/)
- **CME Group — gate passed / score 89:** released Q2 revenue was $1.7B and operating income $1.1B. The result removes the old pending-event gate; product ADV, capture and cloud-transition costs now determine follow-through. [Official Q2 release](https://www.cmegroup.com/media-room/press-releases/2026/7/22/cme_group_inc_reportsstrongfinancialresultsforq22026.html)
- **Persistent Systems:** the board calendar shows 21–22 July for Q1, but a current official result package was not recovered in this run. Its table price is current; the earnings delta is `DATA INSUFFICIENT` and the score was not raised. [Official board calendar](https://www.persistent.com/investors/investors-communication/tentative-bm-calendar/)

## 5. Top 15 India Primary Candidates

| Rank | Company | Ticker | Sector | Primary Use Case | Market Cap | Current Price | MVP Score | Confidence | Casino Role | Chess Piece | Poker Hand | Half-Life | Sovereignty | Mines Risk | Valuation | Entry | Catalyst | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ICICI Bank | NSE:ICICIBANK | Financials | QC | MEGA | ₹1,445.70 | 88 | 94 | HOUSE | QUEEN → QUEEN | FULL HOUSE | VERY LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Q1 fee growth and loan/deposit conversion after a strong official release | Loans grew faster than deposits; future NIM and credit normalization | STRUCTURAL COMPOUNDER |
| 2 | Power Grid Corporation of India | NSE:POWERGRID | Utilities | SR | LARGE | ₹288.85 | 82 | 86 | HOUSE | ROOK → ROOK | FULL HOUSE | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 3 | Shriram Finance | NSE:SHRIRAMFIN | Financials | GR | LARGE | ₹1,038.20 | 82 | 88 | PLAYER | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 4 | IndiaMART InterMESH | NSE:INDIAMART | Communication Services | EC | MID | ₹1,759.70 | 82 | 84 | TABLE | BISHOP → QUEEN | STRAIGHT | LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR CATALYST | Paying-supplier and Busy workflow stabilization | Supplier stagnation, churn and weak reinvestment conversion | WAIT FOR CATALYST |
| 5 | Multi Commodity Exchange of India | NSE:MCX | Financials | SR | MID | ₹2,755.10 | 81 | 84 | HOUSE | ROOK → QUEEN | OVERPLAYED HAND | VERY LONG | 9/10 | 6/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | Q1 volume and revenue-per-contract normalization | Rule shock, premium-turnover loss, regulation and NSE competition | WAIT FOR CATALYST |
| 6 | Bharti Airtel | NSE:BHARTIARTL | Communication Services | BC | MEGA | ₹1,905.30 | 80 | 86 | DEALER | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | BUY-RESEARCH ZONE | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 7 | Indus Towers | NSE:INDUSTOWER | Communication Services | IN | LARGE | ₹387.40 | 80 | 86 | DEALER | ROOK → ROOK | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |
| 8 | Persistent Systems | NSE:PERSISTENT | Information Technology | GR | MID | ₹5,268.20 | 80 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 7/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | Recover and verify the 21–22 July Q1 result package; Nagarro offer milestones | US spending, pricing pressure and multiple compression | WAIT FOR CATALYST |
| 9 | Oracle Financial Services Software | NSE:OFSS | Information Technology | VA | LARGE | ₹11,089.00 | 79 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | VERY LONG | 8/10 | 4/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | License/cloud conversion and product refresh | Oracle-parent dependence, low float and license lumpiness | WAIT FOR PULLBACK |
| 10 | Reliance Industries | NSE:RELIANCE | Energy | BC | MEGA | ₹1,280.00 | 79 | 88 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR CATALYST | Post-Q1 Jio/retail cash conversion and new-energy capex milestones | Capex, O2C cycle, leverage and conglomerate complexity | WAIT FOR CATALYST |
| 11 | Larsen & Toubro | NSE:LT | Industrials | CY | MEGA | ₹3,806.00 | 78 | 87 | DEALER | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | FAIRLY VALUED | BUY-RESEARCH ZONE | ₹7.40T order-book conversion | Project mix, West Asia exposure and working-capital reversal | HIGH-CONVICTION RESEARCH CANDIDATE |
| 12 | Sun Pharmaceutical Industries | NSE:SUNPHARMA | Health Care | DF | LARGE | ₹1,973.70 | 78 | 86 | PLAYER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | Innovative-medicines growth and Organon integration | FDA action, R&D productivity and acquisition execution | WAIT FOR PULLBACK |
| 13 | VA Tech Wabag | NSE:WABAG | Industrials | EC | SMALL | ₹1,977.50 | 77 | 86 | PLAYER | BISHOP → ROOK | STRAIGHT | LONG | 6/10 | 6/10 | FAIRLY VALUED | WAIT FOR PULLBACK | Framework conversion and higher recurring O&M mix | EPC execution, receivables, country risk and extended entry | EARLY CAPTURE |
| 14 | HDFC Bank | NSE:HDFCBANK | Financials | VA | MEGA | ₹739.55 | 77 | 92 | HOUSE | QUEEN → QUEEN | DRAW | VERY LONG | 9/10 | 4/10 | ATTRACTIVE BUT THESIS-DAMAGED | WAIT FOR CATALYST | Evidence that the record-low 3.26% Q1 NIM is a floor, not a new base | Margin compression and modest profit growth despite lower provisions | THESIS WEAKENING |
| 15 | KFin Technologies | NSE:KFINTECH | Financials | EC | MID | ₹949.25 | 74 | 92 | DEALER | BISHOP → ROOK | DRAW | VERY LONG | 7/10 | 5/10 | VALUATION CAUTION AFTER RESULT GAP | WAIT FOR CATALYST | Acquisition-separated organic growth and EBITDA-margin recovery | Acquisition-led revenue and front-loaded costs compressed Q1 EBITDA margin to 34.2% | THESIS WEAKENING |

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

## 6. Top 15 United States Primary Candidates

| Rank | Company | Ticker | Sector | Primary Use Case | Market Cap | Current Price | MVP Score | Confidence | Casino Role | Chess Piece | Poker Hand | Half-Life | Sovereignty | Mines Risk | Valuation | Entry | Catalyst | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Intercontinental Exchange | NYSE:ICE | Financials | SR | LARGE | $145.79 | 89 | 90 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 2 | CME Group | Nasdaq:CME | Financials | IN | LARGE | $255.31 | 89 | 94 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | STRUCTURAL COMPOUNDER |
| 3 | Adobe | Nasdaq:ADBE | Information Technology | VA | LARGE | $225.11 | 87 | 89 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | UNDERVALUED | WAIT FOR CATALYST | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | WAIT FOR CATALYST |
| 4 | Tradeweb Markets | Nasdaq:TW | Financials | GR | LARGE | $99.83 | 87 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Scheduled Q2 release on 30 July; multi-asset share and capture | Fixed-income market share and capture-rate pressure | STRUCTURAL COMPOUNDER |
| 5 | Uber Technologies | NYSE:UBER | Industrials | GR | LARGE | $65.94 | 87 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Scheduled Q2 release on 5 August; AV and FCF conversion | Regulation, insurance costs and AV-platform bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 6 | McKesson | NYSE:MCK | Health Care | QC | LARGE | $840.90 | 87 | 91 | DEALER | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Scheduled FY27 Q1 release on 5 August; oncology/biopharma services mix | CVS/top-ten customer concentration, policy and opioid liabilities | STRUCTURAL COMPOUNDER |
| 7 | BlackRock | NYSE:BLK | Financials | BC | LARGE | $1,055.67 | 86 | 94 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR PULLBACK | HPS/private-markets integration and Aladdin ACV | Market beta, integration and transaction-related dilution | WAIT FOR PULLBACK |
| 8 | CACI International | NYSE:CACI | Industrials | VA | MID | $486.77 | 86 | 89 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 4/10 | UNDERVALUED | BUY-RESEARCH ZONE | Scheduled FY26/FY27 guidance update on 5 August | Federal timing, customer concentration and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |
| 9 | BNY | NYSE:BNY | Financials | DF | LARGE | $158.91 | 85 | 95 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 3/10 | FAIRLY VALUED | WAIT FOR PULLBACK | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | WAIT FOR PULLBACK |
| 10 | Visa | NYSE:V | Financials | BC | MEGA | $355.74 | 85 | 92 | CHIP | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 4/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | Scheduled fiscal Q3 release on 28 July; cross-border and payment volumes | Regulation, litigation, valuation and alternative payment rails | WAIT FOR PULLBACK |
| 11 | Copart | Nasdaq:CPRT | Industrials | QC | LARGE | $27.94 | 84 | 88 | HOUSE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | WAIT FOR CATALYST | Unit and pricing stabilization | Insurer volume weakness and falling returns on land investment | WAIT FOR CATALYST |
| 12 | Toast | NYSE:TOST | Financials | EC | LARGE | $29.04 | 83 | 87 | CHIP | BISHOP → QUEEN | STRAIGHT | LONG | 7/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Retail, international, payroll and non-payment attach | Restaurant cycle, competition, SBC and dilution | EARLY CAPTURE |
| 13 | Veralto | NYSE:VLTO | Industrials | DF | LARGE | $92.02 | 82 | 88 | DEALER | ROOK → ROOK | FULL HOUSE | LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Scheduled Q2 call on 29 July; core growth and acquisition conversion | Organic softness, tariffs and M&A execution | STRUCTURAL COMPOUNDER |
| 14 | Veeva Systems | NYSE:VEEV | Health Care | GR | LARGE | $186.24 | 82 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 4/10 | ATTRACTIVE | WAIT FOR CATALYST | Vault CRM, Data Cloud and AI-agent adoption | CRM transition, pharma budgets and SBC | WAIT FOR CATALYST |
| 15 | MSA Safety | NYSE:MSA | Industrials | QC | MID | $174.64 | 82 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Autronica integration and margin conversion | Industrial cycle, tariffs and acquisition execution | STRUCTURAL COMPOUNDER |

### United States candidate theses and invalidations

1. **ICE — WHY IT REMAINS:** Q1 net revenue rose 20% to $3.0B, operating margin was 56%, adjusted margin 65% and Q1 FCF about $1.15B. Clearing, energy/rates markets, fixed-income data and mortgage workflow are independent made edges. Invalidate on data slowdown, exchange share/capture loss or failed deleveraging. [Official Q1](https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-Reports-Record-First-Quarter-2026/default.aspx)

2. **CME — WHY IT REMAINS:** Q1 revenue rose 14% to $1.9B with a 72.8% adjusted operating margin and $3.36 adjusted EPS. Operating cash flow was $1,259.9M and capex $21.8M, implying conventional FCF near $1,238.1M; cash including FICC was $2.6B versus $3.4B debt. Proprietary liquidity, margin offsets and clearing earn regardless of market direction. Invalidate on persistent ADV/share loss, capture deterioration or adverse rule changes. [Official Q1](https://www.cmegroup.com/media-room/press-releases/2026/4/22/cme_group_inc_reportsrecordrevenueadjustedoperatingincomeadjuste.html)

3. **Adobe — WHY IT REMAINS, WITH A GOVERNANCE DISCOUNT:** FQ2 revenue was $6.62B (+13%), operating cash flow $2.17B and AI-first ARR exceeded $500M. At the 24 July $225.11 close, official FY26 guidance still implies about **12.5x GAAP EPS** or **9.2x non-GAAP EPS**, not the lower unlabeled provider multiple sometimes shown. The market prices severe disruption, but CFO Dan Durn's departure and interim-CFO transition are real mines. Invalidate on ARR deceleration, margin damage or AI products failing to preserve retention/pricing. [Official FQ2 release and guidance](https://www.adobe.com/cc-shared/assets/investor-relations/pdfs/11606202/a5543arefgt.pdf)

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

15. **MSA Safety — WHY IT REMAINS:** Q1 sales were $463.6M (+10% GAAP, +3% organic), operating income $93.0M at 20.1%, net income $71.3M and FCF $65.1M (91% conversion). Cash was $180.2M against $613.1M current and long-term debt, or $433M net debt and 0.9x net leverage, with $1.2B liquidity. At the 24 July $174.64 close the quote is roughly 28.6x the same provider TTM FCF—reasonable only if standards economics and Autronica integration sustain growth. Invalidate on organic contraction, margin below 18% or acquisition leverage/returns disappointing. [Official Q1 release](https://investors.msasafety.com/news-releases/news-release-details/msa-safety-announces-first-quarter-2026-results)

### United States ownership, dilution and concentration gate

- Adobe, Uber, Toast and Veeva require diluted FCF/share and SBC monitoring; adjusted EBITDA alone does not clear the gate.
- ICE, CME, Tradeweb, BNY and Visa face direct regulation, data/capture-rate scrutiny and operational/cyber concentration. House economics do not remove rule risk.
- BlackRock's HPS units raised diluted shares; private-market integration and per-share earnings conversion are explicit gates. McKesson's CVS/top-ten customer concentration and CACI's federal-customer/acquisition leverage are explicit.
- Current Form 4 activity, full institutional-ownership changes and securities-lending concentration were not uniformly refreshed: `LIVE VALIDATION REQUIRED — DATA ACCESS INSUFFICIENT`.

## 7. Additional Discovery Board

### India — 10 additional names

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

### United States — 10 additional names

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

## 8. Early-Capture Board

### India — top 8

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | VA Tech Wabag | NSE:WABAG | India | 77 | 86 | EC | PLAYER | STRAIGHT | LONG | Framework conversion and higher recurring O&M mix | EPC execution, receivables, country risk and extended entry | EARLY CAPTURE |
| 2 | Shriram Finance | NSE:SHRIRAMFIN | India | 82 | 88 | GR | PLAYER | FULL HOUSE | LONG | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 3 | IndiaMART InterMESH | NSE:INDIAMART | India | 82 | 84 | EC | TABLE | STRAIGHT | LONG | Paying-supplier and Busy workflow stabilization | Supplier stagnation, churn and weak reinvestment conversion | WAIT FOR CATALYST |
| 4 | Indus Towers | NSE:INDUSTOWER | India | 80 | 86 | IN | DEALER | FULL HOUSE | VERY LONG | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |
| 5 | HDB Financial Services | NSE:HDBFS | India | 77 | 87 | EC | PLAYER | TWO PAIR | LONG | Promotion proof plus the next current filing | RATE, LIQ, EVT | EARLY CAPTURE |
| 6 | Sagility India | NSE:SAGILITY | India | 76 | 80 | EC | DEALER | TWO PAIR | LONG | Promotion proof plus the next current filing | GEO, LIQ, EVT | RESEARCH DEEPER |
| 7 | Newgen Software Technologies | NSE:NEWGEN | India | 70 | 80 | EC | DEALER | DRAW | LONG | Promotion proof plus the next current filing | LIQ, EVT, BETA | EARLY CAPTURE |
| 8 | KFin Technologies | NSE:KFINTECH | India | 74 | 92 | EC | DEALER | DRAW | VERY LONG | Acquisition-separated organic growth and EBITDA-margin recovery | Acquisition-led revenue and front-loaded costs compressed Q1 EBITDA margin to 34.2% | THESIS WEAKENING |

### United States — top 8

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Toast | NYSE:TOST | United States | 83 | 87 | EC | CHIP | STRAIGHT | LONG | Retail, international, payroll and non-payment attach | Restaurant cycle, competition, SBC and dilution | EARLY CAPTURE |
| 2 | Uber Technologies | NYSE:UBER | United States | 87 | 90 | GR | TABLE | FULL HOUSE | LONG | Scheduled Q2 release on 5 August; AV and FCF conversion | Regulation, insurance costs and AV-platform bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 3 | Guidewire Software | NYSE:GWRE | United States | 79 | 86 | EC | DEALER | STRAIGHT | LONG | Promotion proof plus the next current filing | BETA, EVT, LIQ | EARLY CAPTURE |
| 4 | Samsara | NYSE:IOT | United States | 76 | 88 | EC | DEALER | STRAIGHT | LONG | Promotion proof plus the next current filing | BETA, LIQ, EVT | EARLY CAPTURE |
| 5 | Procore Technologies | NYSE:PCOR | United States | 76 | 86 | EC | DEALER | DRAW | LONG | Promotion proof plus the next current filing | RATE, BETA, LIQ | EARLY CAPTURE |
| 6 | Alkami Technology | Nasdaq:ALKT | United States | 74 | 85 | EC | DEALER | DRAW | LONG | Promotion proof plus the next current filing | RATE, LIQ, EVT | EARLY CAPTURE |
| 7 | Itron | Nasdaq:ITRI | United States | 75 | 83 | EC | PLAYER | STRAIGHT | LONG | Promotion proof plus the next current filing | EVT, REG, BETA | EARLY CAPTURE |
| 8 | NRG Energy | NYSE:NRG | United States | 78 | 87 | CI | PLAYER | TWO PAIR | MEDIUM | Promotion proof plus the next current filing | CMD, RATE, REG | EARLY CAPTURE |

## 9. Current Houses, Tables, Chips, and Rails

### India — top 5

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Power Grid Corporation of India | NSE:POWERGRID | India | 82 | 86 | SR | HOUSE | FULL HOUSE | VERY LONG | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 2 | ICICI Bank | NSE:ICICIBANK | India | 88 | 94 | QC | HOUSE | FULL HOUSE | VERY LONG | Q1 fee growth and loan/deposit conversion after a strong official release | Loans grew faster than deposits; future NIM and credit normalization | STRUCTURAL COMPOUNDER |
| 3 | Multi Commodity Exchange of India | NSE:MCX | India | 81 | 84 | SR | HOUSE | OVERPLAYED HAND | VERY LONG | Q1 volume and revenue-per-contract normalization | Rule shock, premium-turnover loss, regulation and NSE competition | WAIT FOR CATALYST |
| 4 | Bharti Airtel | NSE:BHARTIARTL | India | 80 | 86 | BC | DEALER | FULL HOUSE | VERY LONG | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 5 | Indus Towers | NSE:INDUSTOWER | India | 80 | 86 | IN | DEALER | FULL HOUSE | VERY LONG | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |

### United States — top 5

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Intercontinental Exchange | NYSE:ICE | United States | 89 | 90 | SR | HOUSE | STRAIGHT FLUSH | VERY LONG | Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 2 | CME Group | Nasdaq:CME | United States | 89 | 94 | IN | HOUSE | STRAIGHT FLUSH | VERY LONG | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | STRUCTURAL COMPOUNDER |
| 3 | Visa | NYSE:V | United States | 85 | 92 | BC | CHIP | STRAIGHT FLUSH | VERY LONG | Scheduled fiscal Q3 release on 28 July; cross-border and payment volumes | Regulation, litigation, valuation and alternative payment rails | WAIT FOR PULLBACK |
| 4 | BNY | NYSE:BNY | United States | 85 | 95 | DF | HOUSE | STRAIGHT FLUSH | VERY LONG | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | WAIT FOR PULLBACK |
| 5 | Tradeweb Markets | Nasdaq:TW | United States | 87 | 90 | GR | TABLE | FULL HOUSE | VERY LONG | Scheduled Q2 release on 30 July; multi-asset share and capture | Fixed-income market share and capture-rate pressure | STRUCTURAL COMPOUNDER |

## 10. Combined India + US Top 20

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Intercontinental Exchange | NYSE:ICE | United States | 89 | 90 | SR | HOUSE | STRAIGHT FLUSH | VERY LONG | Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 2 | CME Group | Nasdaq:CME | United States | 89 | 94 | IN | HOUSE | STRAIGHT FLUSH | VERY LONG | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | STRUCTURAL COMPOUNDER |
| 3 | ICICI Bank | NSE:ICICIBANK | India | 88 | 94 | QC | HOUSE | FULL HOUSE | VERY LONG | Q1 fee growth and loan/deposit conversion after a strong official release | Loans grew faster than deposits; future NIM and credit normalization | STRUCTURAL COMPOUNDER |
| 4 | McKesson | NYSE:MCK | United States | 87 | 91 | QC | DEALER | FULL HOUSE | VERY LONG | Scheduled FY27 Q1 release on 5 August; oncology/biopharma services mix | CVS/top-ten customer concentration, policy and opioid liabilities | STRUCTURAL COMPOUNDER |
| 5 | Tradeweb Markets | Nasdaq:TW | United States | 87 | 90 | GR | TABLE | FULL HOUSE | VERY LONG | Scheduled Q2 release on 30 July; multi-asset share and capture | Fixed-income market share and capture-rate pressure | STRUCTURAL COMPOUNDER |
| 6 | Uber Technologies | NYSE:UBER | United States | 87 | 90 | GR | TABLE | FULL HOUSE | LONG | Scheduled Q2 release on 5 August; AV and FCF conversion | Regulation, insurance costs and AV-platform bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 7 | Adobe | Nasdaq:ADBE | United States | 87 | 89 | VA | TABLE | FULL HOUSE | LONG | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | WAIT FOR CATALYST |
| 8 | Power Grid Corporation of India | NSE:POWERGRID | India | 82 | 86 | SR | HOUSE | FULL HOUSE | VERY LONG | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 9 | BlackRock | NYSE:BLK | United States | 86 | 94 | BC | TABLE | FULL HOUSE | VERY LONG | HPS/private-markets integration and Aladdin ACV | Market beta, integration and transaction-related dilution | WAIT FOR PULLBACK |
| 10 | CACI International | NYSE:CACI | United States | 86 | 89 | VA | DEALER | FULL HOUSE | LONG | Scheduled FY26/FY27 guidance update on 5 August | Federal timing, customer concentration and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |
| 11 | Shriram Finance | NSE:SHRIRAMFIN | India | 82 | 88 | GR | PLAYER | FULL HOUSE | LONG | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 12 | BNY | NYSE:BNY | United States | 85 | 95 | DF | HOUSE | STRAIGHT FLUSH | VERY LONG | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | WAIT FOR PULLBACK |
| 13 | IndiaMART InterMESH | NSE:INDIAMART | India | 82 | 84 | EC | TABLE | STRAIGHT | LONG | Paying-supplier and Busy workflow stabilization | Supplier stagnation, churn and weak reinvestment conversion | WAIT FOR CATALYST |
| 14 | Visa | NYSE:V | United States | 85 | 92 | BC | CHIP | STRAIGHT FLUSH | VERY LONG | Scheduled fiscal Q3 release on 28 July; cross-border and payment volumes | Regulation, litigation, valuation and alternative payment rails | WAIT FOR PULLBACK |
| 15 | Multi Commodity Exchange of India | NSE:MCX | India | 81 | 84 | SR | HOUSE | OVERPLAYED HAND | VERY LONG | Q1 volume and revenue-per-contract normalization | Rule shock, premium-turnover loss, regulation and NSE competition | WAIT FOR CATALYST |
| 16 | Bharti Airtel | NSE:BHARTIARTL | India | 80 | 86 | BC | DEALER | FULL HOUSE | VERY LONG | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 17 | Indus Towers | NSE:INDUSTOWER | India | 80 | 86 | IN | DEALER | FULL HOUSE | VERY LONG | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |
| 18 | Persistent Systems | NSE:PERSISTENT | India | 80 | 88 | GR | DEALER | FULL HOUSE | LONG | Recover and verify the 21–22 July Q1 result package; Nagarro offer milestones | US spending, pricing pressure and multiple compression | WAIT FOR CATALYST |
| 19 | Oracle Financial Services Software | NSE:OFSS | India | 79 | 88 | VA | DEALER | FULL HOUSE | VERY LONG | License/cloud conversion and product refresh | Oracle-parent dependence, low float and license lumpiness | WAIT FOR PULLBACK |
| 20 | Reliance Industries | NSE:RELIANCE | India | 79 | 88 | BC | TABLE | FULL HOUSE | VERY LONG | Post-Q1 Jio/retail cash conversion and new-energy capex milestones | Capex, O2C cycle, leverage and conglomerate complexity | WAIT FOR CATALYST |

## 11. Best Risk-Adjusted Ideas

### India — top 5

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ICICI Bank | NSE:ICICIBANK | India | 88 | 94 | QC | HOUSE | FULL HOUSE | VERY LONG | Q1 fee growth and loan/deposit conversion after a strong official release | Loans grew faster than deposits; future NIM and credit normalization | STRUCTURAL COMPOUNDER |
| 2 | Power Grid Corporation of India | NSE:POWERGRID | India | 82 | 86 | SR | HOUSE | FULL HOUSE | VERY LONG | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 3 | Shriram Finance | NSE:SHRIRAMFIN | India | 82 | 88 | GR | PLAYER | FULL HOUSE | LONG | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 4 | Bharti Airtel | NSE:BHARTIARTL | India | 80 | 86 | BC | DEALER | FULL HOUSE | VERY LONG | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 5 | Sun Pharmaceutical Industries | NSE:SUNPHARMA | India | 78 | 86 | DF | PLAYER | FULL HOUSE | LONG | Innovative-medicines growth and Organon integration | FDA action, R&D productivity and acquisition execution | WAIT FOR PULLBACK |

### United States — top 5

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CME Group | Nasdaq:CME | United States | 89 | 94 | IN | HOUSE | STRAIGHT FLUSH | VERY LONG | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | STRUCTURAL COMPOUNDER |
| 2 | Intercontinental Exchange | NYSE:ICE | United States | 89 | 90 | SR | HOUSE | STRAIGHT FLUSH | VERY LONG | Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 3 | Adobe | Nasdaq:ADBE | United States | 87 | 89 | VA | TABLE | FULL HOUSE | LONG | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | WAIT FOR CATALYST |
| 4 | McKesson | NYSE:MCK | United States | 87 | 91 | QC | DEALER | FULL HOUSE | VERY LONG | Scheduled FY27 Q1 release on 5 August; oncology/biopharma services mix | CVS/top-ten customer concentration, policy and opioid liabilities | STRUCTURAL COMPOUNDER |
| 5 | CACI International | NYSE:CACI | United States | 86 | 89 | VA | DEALER | FULL HOUSE | LONG | Scheduled FY26/FY27 guidance update on 5 August | Federal timing, customer concentration and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |

## 12. High Upside, High Mine Density

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

ASTS closed at $55.01 on 16 July, down 17.0% after the convertible announcement. The reset improves pot odds but does not remove constellation, funding or dilution mines; any executable quote still requires live validation. Evidence: [ASTS financing release](https://www.businesswire.com/news/home/20260715000369/en/AST-SpaceMobile-Announces-Proposed-Private-Offering-of-%241.0-Billion-of-Convertible-Senior-Notes-Due-2034), [Rocket Lab Q1](https://investors.rocketlabcorp.com/news-releases/news-release-details/rocket-lab-announces-first-quarter-2026-financial-results), [Applied Digital fiscal Q3](https://ir.applieddigital.com/news-events/press-releases/detail/148/applied-digital-reports-fiscal-third-quarter-2026-results), [Tempus Q1](https://investors.tempus.com/news-releases/news-release-details/tempus-reports-first-quarter-2026-results), and [Hims Q1](https://investors.hims.com/news/news-details/2026/Hims--Hers-Health-Inc--Reports-First-Quarter-2026-Financial-Results/default.aspx).

---

## 13. Queen-Priced Pawns

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

| Company | Freshness | 16 July close / approximate cap | Why expectations outrun the made hand | Label |
|---|---|---|---|---|
| AST SpaceMobile | **NEW DISCOVERY** | $55.01 / $16.4B | Roughly $85M provider TTM revenue, deeply negative FCF and a proposed $1B convertible precede commercial constellation proof | `VALUATION CAUTION` |
| Rocket Lab | RETAINED FROM PRIOR SCREEN | $67.35 / $42.1B | Q1 execution is real, but Neutron success/cadence and high long-run margins are already heavily capitalized versus $200M quarterly revenue | `VALUATION CAUTION` |
| Palantir | RETAINED FROM PRIOR SCREEN | $134.44 / $322.3B | A superb made hand becomes overplayed near roughly 60x EV/revenue and 149x trailing earnings | `VALUATION CAUTION` |
| Robinhood | RETAINED FROM PRIOR SCREEN | $106.02 / $95.5B | Financial-house migration is priced as durable despite crypto/transaction cyclicality and regulatory range | `VALUATION CAUTION` |
| CoreWeave | RETAINED FROM PRIOR SCREEN | $72.91 / $39.8B | Large backlog is not low-risk cash: provider debt near $35B and deeply negative FCF create correlated financing/tenant mines | `VALUATION CAUTION` |
| Tempus AI | RETAINED FROM PRIOR SCREEN | $53.59 / $9.6B | 36% Q1 growth is encouraging, but GAAP loss, SBC and integration risk remain ahead of data-standard economics | `VALUATION CAUTION` |
| IonQ | RETAINED FROM PRIOR SCREEN | $35.10 / $13.1B | Commercial revenue and cash generation remain tiny relative to a valuation assuming useful scaled quantum demand | `VALUATION CAUTION` |

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

## 14. False-Pattern and Hype Traps

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

### Action and catalyst board

| Rank | Company | Ticker | Country | MVP | Confidence | Use Case | Casino Role | Poker | Half-Life | Catalyst / Evidence Gate | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ICICI Bank | NSE:ICICIBANK | India | 88 | 94 | QC | HOUSE | FULL HOUSE | VERY LONG | Q1 fee growth and loan/deposit conversion after a strong official release | Loans grew faster than deposits; future NIM and credit normalization | STRUCTURAL COMPOUNDER |
| 2 | Power Grid Corporation of India | NSE:POWERGRID | India | 82 | 86 | SR | HOUSE | FULL HOUSE | VERY LONG | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 3 | Shriram Finance | NSE:SHRIRAMFIN | India | 82 | 88 | GR | PLAYER | FULL HOUSE | LONG | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 4 | IndiaMART InterMESH | NSE:INDIAMART | India | 82 | 84 | EC | TABLE | STRAIGHT | LONG | Paying-supplier and Busy workflow stabilization | Supplier stagnation, churn and weak reinvestment conversion | WAIT FOR CATALYST |
| 5 | Multi Commodity Exchange of India | NSE:MCX | India | 81 | 84 | SR | HOUSE | OVERPLAYED HAND | VERY LONG | Q1 volume and revenue-per-contract normalization | Rule shock, premium-turnover loss, regulation and NSE competition | WAIT FOR CATALYST |
| 6 | Bharti Airtel | NSE:BHARTIARTL | India | 80 | 86 | BC | DEALER | FULL HOUSE | VERY LONG | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 7 | Indus Towers | NSE:INDUSTOWER | India | 80 | 86 | IN | DEALER | FULL HOUSE | VERY LONG | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |
| 8 | Persistent Systems | NSE:PERSISTENT | India | 80 | 88 | GR | DEALER | FULL HOUSE | LONG | Recover and verify the 21–22 July Q1 result package; Nagarro offer milestones | US spending, pricing pressure and multiple compression | WAIT FOR CATALYST |
| 9 | Oracle Financial Services Software | NSE:OFSS | India | 79 | 88 | VA | DEALER | FULL HOUSE | VERY LONG | License/cloud conversion and product refresh | Oracle-parent dependence, low float and license lumpiness | WAIT FOR PULLBACK |
| 10 | Reliance Industries | NSE:RELIANCE | India | 79 | 88 | BC | TABLE | FULL HOUSE | VERY LONG | Post-Q1 Jio/retail cash conversion and new-energy capex milestones | Capex, O2C cycle, leverage and conglomerate complexity | WAIT FOR CATALYST |
| 11 | Larsen & Toubro | NSE:LT | India | 78 | 87 | CY | DEALER | FULL HOUSE | LONG | ₹7.40T order-book conversion | Project mix, West Asia exposure and working-capital reversal | HIGH-CONVICTION RESEARCH CANDIDATE |
| 12 | Sun Pharmaceutical Industries | NSE:SUNPHARMA | India | 78 | 86 | DF | PLAYER | FULL HOUSE | LONG | Innovative-medicines growth and Organon integration | FDA action, R&D productivity and acquisition execution | WAIT FOR PULLBACK |
| 13 | VA Tech Wabag | NSE:WABAG | India | 77 | 86 | EC | PLAYER | STRAIGHT | LONG | Framework conversion and higher recurring O&M mix | EPC execution, receivables, country risk and extended entry | EARLY CAPTURE |
| 14 | HDFC Bank | NSE:HDFCBANK | India | 77 | 92 | VA | HOUSE | DRAW | VERY LONG | Evidence that the record-low 3.26% Q1 NIM is a floor, not a new base | Margin compression and modest profit growth despite lower provisions | THESIS WEAKENING |
| 15 | KFin Technologies | NSE:KFINTECH | India | 74 | 92 | EC | DEALER | DRAW | VERY LONG | Acquisition-separated organic growth and EBITDA-margin recovery | Acquisition-led revenue and front-loaded costs compressed Q1 EBITDA margin to 34.2% | THESIS WEAKENING |
| 16 | Intercontinental Exchange | NYSE:ICE | United States | 89 | 90 | SR | HOUSE | STRAIGHT FLUSH | VERY LONG | Scheduled Q2 release on 30 July; clearing, data, mortgage workflow and leverage | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 17 | CME Group | Nasdaq:CME | United States | 89 | 94 | IN | HOUSE | STRAIGHT FLUSH | VERY LONG | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | STRUCTURAL COMPOUNDER |
| 18 | Adobe | Nasdaq:ADBE | United States | 87 | 89 | VA | TABLE | FULL HOUSE | LONG | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | WAIT FOR CATALYST |
| 19 | Tradeweb Markets | Nasdaq:TW | United States | 87 | 90 | GR | TABLE | FULL HOUSE | VERY LONG | Scheduled Q2 release on 30 July; multi-asset share and capture | Fixed-income market share and capture-rate pressure | STRUCTURAL COMPOUNDER |
| 20 | Uber Technologies | NYSE:UBER | United States | 87 | 90 | GR | TABLE | FULL HOUSE | LONG | Scheduled Q2 release on 5 August; AV and FCF conversion | Regulation, insurance costs and AV-platform bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 21 | McKesson | NYSE:MCK | United States | 87 | 91 | QC | DEALER | FULL HOUSE | VERY LONG | Scheduled FY27 Q1 release on 5 August; oncology/biopharma services mix | CVS/top-ten customer concentration, policy and opioid liabilities | STRUCTURAL COMPOUNDER |
| 22 | BlackRock | NYSE:BLK | United States | 86 | 94 | BC | TABLE | FULL HOUSE | VERY LONG | HPS/private-markets integration and Aladdin ACV | Market beta, integration and transaction-related dilution | WAIT FOR PULLBACK |
| 23 | CACI International | NYSE:CACI | United States | 86 | 89 | VA | DEALER | FULL HOUSE | LONG | Scheduled FY26/FY27 guidance update on 5 August | Federal timing, customer concentration and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |
| 24 | BNY | NYSE:BNY | United States | 85 | 95 | DF | HOUSE | STRAIGHT FLUSH | VERY LONG | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | WAIT FOR PULLBACK |
| 25 | Visa | NYSE:V | United States | 85 | 92 | BC | CHIP | STRAIGHT FLUSH | VERY LONG | Scheduled fiscal Q3 release on 28 July; cross-border and payment volumes | Regulation, litigation, valuation and alternative payment rails | WAIT FOR PULLBACK |
| 26 | Copart | Nasdaq:CPRT | United States | 84 | 88 | QC | HOUSE | FULL HOUSE | VERY LONG | Unit and pricing stabilization | Insurer volume weakness and falling returns on land investment | WAIT FOR CATALYST |
| 27 | Toast | NYSE:TOST | United States | 83 | 87 | EC | CHIP | STRAIGHT | LONG | Retail, international, payroll and non-payment attach | Restaurant cycle, competition, SBC and dilution | EARLY CAPTURE |
| 28 | Veralto | NYSE:VLTO | United States | 82 | 88 | DF | DEALER | FULL HOUSE | LONG | Scheduled Q2 call on 29 July; core growth and acquisition conversion | Organic softness, tariffs and M&A execution | STRUCTURAL COMPOUNDER |
| 29 | Veeva Systems | NYSE:VEEV | United States | 82 | 90 | GR | TABLE | FULL HOUSE | LONG | Vault CRM, Data Cloud and AI-agent adoption | CRM transition, pharma budgets and SBC | WAIT FOR CATALYST |
| 30 | MSA Safety | NYSE:MSA | United States | 82 | 88 | QC | DEALER | FULL HOUSE | LONG | Autronica integration and margin conversion | Industrial cycle, tariffs and acquisition execution | STRUCTURAL COMPOUNDER |

## 15. Final Daily Synthesis

| No. | Required Selection | Winner | Why | What Market May Be Missing | Catalyst | Invalidation | Evidence Needed Next |
|---|---|---|---|---|---|---|---|
| 1 | Best India opportunity today | ICICI Bank (NSE:ICICIBANK) | Highest India blend of capital, underwriting, customer ownership and pot odds after a strong Q1. | Fee growth, stable NIM and capital can persist without a heroic rate or credit assumption. | Q1 loan, deposit and fee conversion into the next quarter. | NIM persistently below 4%, deposit funding deteriorates, or renewed slippage. | Deposit cohorts, fee mix, credit cost, CET1 and segment ROA. |
| 2 | Best US opportunity today | Intercontinental Exchange (NYSE:ICE) | Best overall score and broadest diversified House at a defensible valuation. | Mortgage weakness obscures clearing, energy/rates, data and workflow compounding. | Confirmed Q2 on 30 July. | Data slowdown, share/capture loss or deleveraging failure. | Segment organic growth, mortgage revenue, FCF and net-debt bridge. |
| 3 | Best India early-capture opportunity | VA Tech Wabag (NSE:WABAG) | Net cash, audited FCF and recurring O&M can promote a project contractor into a water-infrastructure Rook. | Scarce treatment capability and O&M mix can outlive individual EPC awards. | Framework-to-firm-order conversion, collections and O&M mix. | Receivables re-expand, overseas execution losses recur, or framework conversion fails. | Firm orders, receivable ageing, cash collection, O&M revenue and promoter/pledge refresh. |
| 4 | Best US early-capture opportunity | Toast (NYSE:TOST) | ARR, location and GPV growth now coexist with positive FCF. | Retail, international, payroll and capital attach can widen value per location. | Next result and attach-rate disclosure. | Location/GPV growth below mid-teens or SBC blocks per-share conversion. | Cohort retention, recurring gross profit, SBC/share and international economics. |
| 5 | Best India structural house/table/rail | Power Grid Corporation of India (NSE:POWERGRID) | An unavoidable regulated transmission rail earns across competing generation winners. | Renewable evacuation converts capex into regulated assets rather than a directional power bet. | Project capitalization and awards. | Allowed-return damage, commissioning delay or debt outruns earnings. | Project capitalization, CWIP, leverage and regulated-return schedule. |
| 6 | Best US structural house/table/rail | Intercontinental Exchange (NYSE:ICE) | Clearing permission, proprietary liquidity, data and workflow form the broadest House. | Four reinforcing rails make earnings less volume-dependent than the exchange label implies. | Confirmed Q2 on 30 July. | Regulatory economics change or recurring data loses pricing/share. | Data retention, clearing share, mortgage workflow and leverage. |
| 7 | Best India risk-adjusted opportunity | ICICI Bank (NSE:ICICIBANK) | Highest combination of sovereignty, evidence, valuation and mine survival. | The balance sheet does not require a repair thesis. | Q1 deposit/NIM evidence. | Deposit franchise weakens or credit cost rises sharply. | Deposit cohorts, LCR, CET1, credit cost and segment ROA. |
| 8 | Best US risk-adjusted opportunity | CME Group (Nasdaq:CME) | Released Q2 revenue of $1.7B, benchmark liquidity, clearing and exceptional margins support low mine density. | Product depth and collateral efficiency can compound without permanently higher volatility. | Post-Q2 ADV, open-interest and market-data follow-through. | Persistent ADV/share loss or capture deterioration. | Product ADV, open interest, capture, expenses, cloud-transition costs and capital return. |
| 9 | Highest-upside India candidate | Kaynes Technology (NSE:KAYNES) | Successful OSAT/critical-electronics promotion could change both role and addressable market. | Platform value is possible only after qualification and utilization—not yet made. | Customer qualification and capex commissioning. | Funding stress, delay, low utilization or persistent negative post-capex FCF. | Binding customers, yields, utilization, funding stack and audited FCF bridge. |
| 10 | Highest-upside US candidate | AST SpaceMobile (Nasdaq:ASTS) | Direct-to-device service could become a global telecom layer. | Partner distribution may lower customer-acquisition needs if the constellation works. | Funding terms, launch cadence and first recurring commercial revenue. | Launch/technical failure, underfunding or dilution overwhelms per-share value. | Final financing, uptime, service revenue and funded deployment. |
| 11 | Most attractively valued India candidate | HDFC Bank (NSE:HDFCBANK) | The post-result selloff creates the largest valuation discount in the quality-bank cohort, but this is a damaged-thesis value candidate, not a clean winner. | The market may be over-extrapolating the record-low 3.26% Q1 NIM; evidence of a floor is still absent. | A quarter of NIM stabilization, deposit mix improvement and better core pre-provision growth. | Another material NIM decline, deposit underperformance or stalled ROA normalization. | Average-balance NIM, deposit mix, normalized provisions, ROA, costs and asset quality. |
| 12 | Most attractively valued US candidate | Adobe (Nasdaq:ADBE) | Low official-guidance earnings pot odds with substantial cash generation. | AI can be an upsell and retention tool, not only a substitute. | AI ARR, retention and permanent CFO succession. | ARR deceleration, margin damage or AI erodes pricing/retention. | Product AI ARR, renewal cohorts, inference cost, SBC and FCF. |
| 13 | Most overpriced pawn | IonQ (NYSE:IONQ) | Commercial cash evidence remains tiny relative to a valuation assuming scaled quantum demand. | Technical progress is not yet repeatable cash-generating standard control. | Commercial revenue and error-correction evidence. | Scaled customer use and positive unit economics arrive much sooner than expected. | Production workloads, bookings conversion, burn and dilution. |
| 14 | Best matrix segment winner overall | Intercontinental Exchange (NYSE:ICE) | It wins Structural Rail, House, Very-Long Half-Life and overall score without heroic entry assumptions. | The combined ecosystem is broader than the exchange label. | Confirmed Q2 on 30 July. | Multi-segment organic growth or cash conversion weakens materially. | Segment revenue, recurring data, clearing share, FCF and debt. |
| 15 | Best under-followed India discovery | Shriram Finance (NSE:SHRIRAMFIN) | Mid-teens AUM growth and normalized profit growth at attractive pot odds. | The franchise may be evolving beyond specialist vehicle lending. | Funding-cost and credit-cost normalization. | Stage 2/3 rises, collections weaken or funding advantage disappears. | Vintages, collections, Stage 2/3, ECL and ALM schedule. |
| 16 | Best under-followed US discovery | BNY (NYSE:BNY) | Fresh fee growth, platform margin and 31.3% ROTCE show converted operating leverage. | It remains framed as a rate-sensitive custodian rather than settlement/collateral infrastructure. | Fee-led growth after the result gap. | Fee/margin reversal, CET1 pressure or a major cyber event. | Organic fee/NII bridge, platform expenses, CET1 and buybacks. |

### 17. Top 10 companies requiring immediate deeper research

| Rank | Company | Ticker | Why Now / Evidence Needed | Main Mine | Thesis Invalidation | Action |
|---|---|---|---|---|---|---|
| 1 | HDFC Bank | NSE:HDFCBANK | Evidence that the record-low 3.26% Q1 NIM is a floor, not a new base | Margin compression and modest profit growth despite lower provisions | Another material NIM decline, deposit underperformance, or stalled ROA normalization | THESIS WEAKENING |
| 2 | CME Group | Nasdaq:CME | Q2 product ADV, open-interest and market-data follow-through | Volume/capture normalization, new competition, cloud-transition and rule risk | Persistent ADV/share loss, capture deterioration, or adverse clearing economics | STRUCTURAL COMPOUNDER |
| 3 | KFin Technologies | NSE:KFINTECH | Acquisition-separated organic growth and EBITDA-margin recovery | Acquisition-led revenue and front-loaded costs compressed Q1 EBITDA margin to 34.2% | Margin fails to recover above 36% or acquisition-separated growth falls below 15% for two quarters | THESIS WEAKENING |
| 4 | VA Tech Wabag | NSE:WABAG | Framework conversion and higher recurring O&M mix | EPC execution, receivables, country risk and extended entry | Receivables re-expand, overseas losses recur, or framework conversion fails | EARLY CAPTURE |
| 5 | Shriram Finance | NSE:SHRIRAMFIN | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | Stage 2/3 rises materially, collections weaken, or liability-duration stress appears | HIGH-CONVICTION RESEARCH CANDIDATE |
| 6 | BNY | NYSE:BNY | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | Organic fees slow, margins reverse, CET1 comes under pressure, or a major cyber event occurs | WAIT FOR PULLBACK |
| 7 | Adobe | Nasdaq:ADBE | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | ARR decelerates, margins weaken, or AI products fail to preserve retention/pricing | WAIT FOR CATALYST |
| 8 | Reliance Industries | NSE:RELIANCE | Post-Q1 Jio/retail cash conversion and new-energy capex milestones | Capex, O2C cycle, leverage and conglomerate complexity | Sustained negative FCF, leverage escalation, or Jio/retail growth below high single digits | WAIT FOR CATALYST |
| 9 | Copart | Nasdaq:CPRT | Unit and pricing stabilization | Insurer volume weakness and falling returns on land investment | Units remain weak without price/share gains, or land investment ceases to earn attractive returns | WAIT FOR CATALYST |
| 10 | Indus Towers | NSE:INDUSTOWER | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | Collections fail, lease-adjusted leverage worsens, or overseas capex destroys ROIC | STRUCTURAL COMPOUNDER |

## Quality-Control Audit

- **PASS:** only India and United States issuers; eligible exchanges only.
- **PASS:** 15 India and 15 US primary candidates; 10+10 additional boards; 10/10 combined Top 20.
- **PASS:** no duplicate ticker in primary rankings.
- **PASS:** all 10 segment groups and 73 requested segment rows are present.
- **PASS:** weak segments explicitly use `NO QUALIFIED WINNER TODAY`; MICRO/NANO, distressed and unsupported turnaround/special situations are not force-filled.
- **PASS:** all primary score vectors sum to their 100-point totals; confidence is separate.
- **PASS:** prices are dated observations; no executable or fabricated price is implied.
- **PASS:** JSON parse and CSV row checks are enforced by the generator and fail closed.
- **PASS:** no commit, push or production-code modification.

The daily answer is the overlap of control, cash conversion, sovereignty, reasonable pot odds and survivable mines—not the loudest multiplier. Today that favors **ICE, CME, ICICI Bank, Power Grid, McKesson and CACI**; the cleaner earlier-capture paths are **Wabag, Toast, Shriram Finance and IndiaMART**.

`MATRIX WINNER DISCOVERY COMPLETE`
