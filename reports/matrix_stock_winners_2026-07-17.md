# Sleeping Passenger — India + United States Matrix Winner Discovery

> **Advisory research only. No investment is guaranteed.** Scores rank research priority and weighted evidence; they are not target returns or trade instructions.

> `LIVE VALIDATION REQUIRED` for executable prices, promoter/pledge and related-party fields, current Form 4/13F activity, complete estimate revisions, and any ownership field not explicitly linked to a current filing.

## 1. Analysis Metadata

- **Analysis date:** 2026-07-17
- **Generation time:** 2026-07-17 12:11:35 India Standard Time+0530, Asia/Calcutta
- **India market status:** **OPEN — regular NSE/BSE cash session**
- **United States market status:** **CLOSED — latest validated prices are 16 July closes**
- **Scope:** India—NSE/BSE; United States—NYSE, Nasdaq and NYSE American. Foreign ADRs and every other country are excluded.
- **Equal-depth rule:** 15 India and 15 US primary candidates; 10 India and 10 US additional discoveries; every segment has separate India and US fields.
- **Price basis:** India primary quotes are read-only observations from 17 July at 11:50 IST; the official NSE index map was observed at 12:02 IST. US primary prices are 16 July regular-session closes. They are not executable bids/offers.
- **Data sources:** [official NSE all-indices feed](https://www.nseindia.com/api/allIndices), Yahoo/yfinance read-only OHLCV, [SEC EDGAR](https://www.sec.gov/edgar/search/), company investor-relations releases and the sourced [latest fully sourced discovery evidence spine](daily_stock_discovery_2026-07-16.md).
- **Financial periods:** India FY2025-26/Q1 FY2026-27 where released; US Q1/Q2/FY2026 as identified in each linked release.
- **Confidence:** separate from opportunity. It discounts stale fields, source disagreement, transparency gaps, limited samples and forecast uncertainty.
- **GICS:** all 11 official broad sectors are used. Industry group/industry/sub-industry are working GICS-normalized mappings and should be rechecked against a licensed constituent file before production use.

### Repository recovery and discipline

- Branch: `sprint/open-the-gate-gap-closer`.
- Baseline worktree was already dirty: six tracked files modified plus prior reports and `tmp/` untracked. Those changes were preserved.
- Reused: `fresh_market_discovery.py`, `daily_scoring.py`, `minimum_daily_universe.py`, market/Yahoo adapters, ticker resolution, OHLCV utilities, and prior report conventions.
- Existing isolated 100-point matrix builder and 16 July evidence spine were reused; no production application code was modified.
- Change made: the report builder was minimally refreshed for 17 July prices, market maps, evidence dates and validation metadata; no commit or push.
- Live-source audit: the official NSE all-indices feed was reachable at 12:02 IST and Yahoo worked for bounded India intraday/US closing-price refreshes. The repository's 17 July daily payload remained a seeded static fallback, so it was excluded as live evidence.
- Dependency audit: Python and the existing yfinance/pandas report path executed successfully. Report syntax, JSON parsing, CSV rows and matrix invariants are validated by the builder.

### Data limitations

No consolidated real-time feed/order book, full estimate-history database, uniformly current promoter/insider/institutional feed, or active multi-provider quote fallback was available. India promoter encumbrance, FII/DII, auditor/RPT and free-float fields, and US SBC/Form 4/customer/cloud concentration fields were included only when filing-supported; otherwise they remain a next-evidence gate. Bank/NBFC/insurer conventional FCF is not used as though it were industrial-company FCF.

## 2. India Market Map

- **Condition:** narrow large-cap risk-on with weak breadth. At the official 12:02 IST snapshot, Nifty 50 was **+0.81%**, Nifty 500 **+0.13%**, Midcap 100 **-0.74%**, and Nifty 500 breadth was only **124 advances / 374 declines**; India VIX was **13.29 (+3.12%)**. [Official NSE feed](https://www.nseindia.com/api/allIndices)
- **Leadership:** Private Banks **+1.47%**, IT **+1.24%**, Financial Services **+1.02%** and Banks **+0.89%** led; Pharma **-1.67%**, Healthcare **-1.48%**, Midcaps **-0.74%** and Metals **-0.61%** lagged.
- **Macro drivers:** June CPI 4.38% YoY, June WPI 9.87%, RBI repo 5.25%, oil/INR and geopolitical freight risk. [Official CPI release](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2284125&lang=1&reg=1), [official WPI release](https://eaindustry.nic.in/press_release/press_release_202607.pdf)
- **Strongest areas:** well-capitalized lenders; capital-market/registry rails; transmission; telecom towers/data; water infrastructure; selective digital engineering; auto only where cash and share evidence convert.
- **Avoid/discount:** leveraged renewables, order-book stories without cash, weak-governance microcaps, oil-sensitive airlines and queen-priced EMS/semiconductor narratives.
- **Risk appetite:** selective and top-heavy. Rising VIX plus 374 Nifty 500 decliners make evidence, liquidity and event gates more important than the positive headline index.

## 3. United States Market Map

- **Condition:** near-record but concentration-sensitive. On 16 July the S&P 500 fell **0.5%**, Dow **0.2%**, Nasdaq **1.5%** and Russell 2000 **0.1%**. [Market close report](https://apnews.com/article/wall-street-stocks-dow-nasdaq-b2a85bf17cbb4653ba83bb7c655366c0)
- **Leadership:** broader participation was firmer than the cap-weighted headline, while chip and other AI winners drove the Nasdaq drawdown; financial infrastructure and recurring industrial services remain the preferred non-consensus cohorts.
- **Macro drivers:** June PPI -0.3% MoM but +5.5% YoY, rising bond yields, oil/geopolitical volatility, the 28–29 July FOMC meeting and Q2 earnings. [Official BLS PPI](https://www.bls.gov/news.release/archives/ppi_07152026.htm)
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
| NSE:ICICIBANK | 9/9/8/11/7/8/6/5/6/6/5/4/2 | 86 |
| NSE:HDFCBANK | 9/9/7/11/8/8/7/4/5/5/5/4/2 | 84 |
| NSE:POWERGRID | 10/9/5/11/5/8/7/5/6/5/5/4/2 | 82 |
| NSE:SHRIRAMFIN | 8/8/8/10/7/8/7/5/6/5/5/3/2 | 82 |
| NSE:INDIAMART | 8/8/10/9/8/9/6/5/6/5/4/3/1 | 82 |
| NSE:MCX | 10/9/8/11/8/4/7/3/6/4/5/4/2 | 81 |
| NSE:KFINTECH | 8/7/10/10/7/6/7/4/6/5/5/4/2 | 81 |
| NSE:BHARTIARTL | 9/8/7/11/6/5/7/5/6/5/5/4/2 | 80 |
| NSE:INDUSTOWER | 9/8/6/10/7/8/6/5/6/5/5/3/2 | 80 |
| NSE:PERSISTENT | 7/7/9/11/7/6/7/5/6/5/4/4/2 | 80 |
| NSE:OFSS | 8/8/8/10/8/6/6/3/6/5/5/4/2 | 79 |
| NSE:RELIANCE | 9/8/8/10/6/7/6/5/5/4/5/4/2 | 79 |
| NSE:LT | 8/8/7/11/6/6/8/4/5/4/5/4/2 | 78 |
| NSE:SUNPHARMA | 8/8/7/11/8/5/7/4/5/5/4/4/2 | 78 |
| NSE:WABAG | 7/6/10/10/7/6/7/4/5/4/5/4/2 | 77 |
| NYSE:ICE | 10/9/7/12/8/8/7/4/7/6/5/4/2 | 89 |
| Nasdaq:CME | 10/9/6/12/8/8/7/4/7/6/5/4/2 | 88 |
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
| VA — Value | HDFC Bank (NSE:HDFCBANK) | Adobe (Nasdaq:ADBE) | Adobe (Nasdaq:ADBE) | CACI International (NYSE:CACI) | 87 | 89 | Official FY26 guidance implies unusually low earnings pot odds despite substantial cash generation and real AI-first ARR. | AI displacement and management transition. | WAIT FOR CATALYST |
| IN — Income | Power Grid Corporation of India (NSE:POWERGRID) | CME Group (Nasdaq:CME) | CME Group (Nasdaq:CME) | Indus Towers (NSE:INDUSTOWER) | 88 | 91 | Benchmark liquidity, clearing and exceptional cash economics support distributions without requiring directional market calls. | ADV/capture normalization and rule changes. | STRUCTURAL COMPOUNDER |
| BC — Blue-chip core | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | 86 | 89 | Capital, underwriting, deposits and payments combine with better entry pot odds than the premium-priced US network. | Deposit and credit normalization. | STRUCTURAL COMPOUNDER |
| DF — Defensive | Sun Pharmaceutical Industries (NSE:SUNPHARMA) | Veralto (NYSE:VLTO) | Veralto (NYSE:VLTO) | McKesson (NYSE:MCK) | 82 | 88 | Regulated water/product-quality measurement has high recurring mix, low mine density and long installed-base life. | Organic softness, tariffs and acquisition execution. | STRUCTURAL COMPOUNDER |
| CY — Cyclical | Larsen & Toubro (NSE:LT) | NRG Energy (NYSE:NRG) | Larsen & Toubro (NSE:LT) | NRG Energy (NYSE:NRG) | 78 | 87 | Large diversified order book and improving working capital provide converted evidence across the capex cycle. | Project mix, geopolitics and cash conversion. | HIGH-CONVICTION RESEARCH CANDIDATE |
| MO — Momentum | NO QUALIFIED WINNER TODAY | BNY (NYSE:BNY) | BNY (NYSE:BNY) | NO QUALIFIED WINNER TODAY | 85 | 95 | Fresh Q2 fee growth, margin expansion and a result-day breakout are evidence-backed, but the gap weakens entry. | Gap failure, NII reversal and fee regulation. | WAIT FOR PULLBACK |
| EC — Early capture | KFin Technologies (NSE:KFINTECH) | Toast (NYSE:TOST) | Toast (NYSE:TOST) | KFin Technologies (NSE:KFINTECH) | 83 | 87 | Positive FCF and 20%+ operating growth support a real POS/payment Dealer-to-commerce-Table path. | Restaurant cycle, competition and dilution. | EARLY CAPTURE |
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
| MEGA | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | ICICI Bank (NSE:ICICIBANK) | QC | 86 | 89 | Pass—deep institutional liquidity; executable quote still requires revalidation. | Deposit/NIM and credit cycle. | STRUCTURAL COMPOUNDER |
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
| HV — High volatility | KFin Technologies (NSE:KFINTECH) | Adobe (Nasdaq:ADBE) | Adobe (Nasdaq:ADBE) | VA | 87 | 89 | Large cash generation and low implied expectations compensate for volatility better than pre-profit peers. | Require ARR/retention evidence; avoid catalyst-size exposure. | WAIT FOR CATALYST |

### 4.6 Risk-sensitivity winners

| Risk Tag | Best India | Best US | Best Overall | Use Case | MVP Score | Confidence | Why Exposure Is Attractive | Main Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| BETA | Larsen & Toubro (NSE:LT) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | GR | 87 | 90 | Cash-generating platform leverage rather than pre-profit beta. | Macro slowdown and regulation. | HIGH-CONVICTION RESEARCH CANDIDATE |
| LIQ | VA Tech Wabag (NSE:WABAG) | NO QUALIFIED WINNER TODAY | VA Tech Wabag (NSE:WABAG) | EC | 77 | 86 | Potential small-cap rerating after order-to-cash proof. | Spread, ownership validation and receivables. | EARLY CAPTURE |
| EVT | HDFC Bank (NSE:HDFCBANK) | CME Group (Nasdaq:CME) | CME Group (Nasdaq:CME) | IN | 88 | 91 | Confirmed evidence checkpoint on 22 July. | ADV/capture disappointment. | STRUCTURAL COMPOUNDER |
| CMD | Himadri Speciality Chemical (NSE:HSCL) | NRG Energy (NYSE:NRG) | NRG Energy (NYSE:NRG) | CI | 78 | 87 | Several paths beyond spot commodity direction. | ERCOT, hedge book and leverage. | EARLY CAPTURE |
| RATE | ICICI Bank (NSE:ICICIBANK) | BNY (NYSE:BNY) | ICICI Bank (NSE:ICICIBANK) | QC | 86 | 89 | Rate exposure buffered by capital, fees and customer ownership. | Deposit competition and NIM compression. | STRUCTURAL COMPOUNDER |
| REG | Power Grid Corporation of India (NSE:POWERGRID) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | SR | 89 | 90 | Permissioned market infrastructure with diversified revenue. | Adverse rule economics or compliance/cyber failure. | STRUCTURAL COMPOUNDER |
| GEO | Larsen & Toubro (NSE:LT) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | VA | 86 | 89 | Embedded access and differentiated systems, not only a defence label. | Federal timing, budget priorities and leverage. | HIGH-CONVICTION RESEARCH CANDIDATE |

### 4.7 Structural-role winners

| Casino Role | Best India | Best US | Best Overall | Sector | MVP Score | Confidence | Why Winner | Valuation Risk | Action |
|---|---|---|---|---|---|---|---|---|---|
| PLAYER | Shriram Finance (NSE:SHRIRAMFIN) | NRG Energy (NYSE:NRG) | Shriram Finance (NSE:SHRIRAMFIN) | Financials | 82 | 88 | The lending Player has better current valuation and converted profit growth than high-mine operating Players. | Moderate; credit-cycle discount is warranted. | HIGH-CONVICTION RESEARCH CANDIDATE |
| DEALER | KFin Technologies (NSE:KFINTECH) | McKesson (NYSE:MCK) | McKesson (NYSE:MCK) | Health Care | 87 | 91 | Essential healthcare distribution earns repeatedly and is adding higher-margin services. | Low/moderate versus converted FCF. | STRUCTURAL COMPOUNDER |
| TABLE | IndiaMART InterMESH (NSE:INDIAMART) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | Industrials | 87 | 90 | Marketplace liquidity now converts into cash while ads, membership and AV distribution widen capture. | Moderate; growth must remain mid-teens or better. | HIGH-CONVICTION RESEARCH CANDIDATE |
| HOUSE | ICICI Bank (NSE:ICICIBANK) | Intercontinental Exchange (NYSE:ICE) | Intercontinental Exchange (NYSE:ICE) | Financials | 89 | 90 | Rules, access, clearing, data and workflows form the strongest multi-rail House. | Moderate; non-heroic but Q2 must confirm. | STRUCTURAL COMPOUNDER |
| CHIP | ICICI Bank (NSE:ICICIBANK) | Visa (NYSE:V) | Visa (NYSE:V) | Financials | 85 | 92 | Global authorization and settlement collect across commerce with exceptional margins and ubiquity. | High near the annual high. | WAIT FOR PULLBACK |

### 4.8 Chess-promotion winners

| Chess Segment | Best India | Best US | Best Overall | Promotion Probability | Time Horizon | Main Milestone | Main Mine | Action |
|---|---|---|---|---|---|---|---|---|
| Best current PAWN | Newgen Software Technologies (NSE:NEWGEN) | Itron (Nasdaq:ITRI) | Itron (Nasdaq:ITRI) | 55% | 3–5 years | Outcomes growth, backlog stabilization and repeatable FCF | Utility deployment timing | EARLY CAPTURE |
| Best current KNIGHT | HDB Financial Services (NSE:HDBFS) | Kinsale Capital (NYSE:KNSL) | Kinsale Capital (NYSE:KNSL) | 55% | 3–5 years | Sustain underwriting discipline through softer pricing | Reserve/catastrophe correlation | WATCHLIST |
| Best current BISHOP | KFin Technologies (NSE:KFINTECH) | CACI International (NYSE:CACI) | CACI International (NYSE:CACI) | 60% | 3–5 years | Mission mix and FCF/share compound | Award timing | HIGH-CONVICTION RESEARCH CANDIDATE |
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
| TERTIARY CONSUMER | KFin Technologies (NSE:KFINTECH) | Uber Technologies (NYSE:UBER) | Uber Technologies (NYSE:UBER) | Marketplace liquidity, memberships, ads and AV distribution. | 87 | 90 | Owns customer discovery/liquidity and collects across local commerce participants. | Regulation, insurance and bypass. | HIGH-CONVICTION RESEARCH CANDIDATE |
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
NSE:HDFCBANK | India | NSE | Financials > Banks > Banks > Diversified Banks | VA | QC, BC | MEGA | M5 | COM | LV | RATE, REG, EVT
NSE:POWERGRID | India | NSE | Utilities > Utilities > Electric Utilities > Electric Transmission | SR | IN, DF | LARGE | M6 | COM | LV | RATE, REG
NSE:SHRIRAMFIN | India | NSE | Financials > Financial Services > Consumer Finance > Diversified Finance | GR | VA, EC | LARGE | M4 | COM | HV | RATE, BETA, LIQ
NSE:INDIAMART | India | NSE | Communication Services > Media & Entertainment > Interactive Media & Services > B2B Marketplace | EC | QC, SR | MID | M4 | COM | HV | BETA, REG
NSE:MCX | India | NSE | Financials > Financial Services > Capital Markets > Financial Exchanges & Data | SR | QC, MO | MID | M5 | COM | HV | REG, EVT, CMD
NSE:KFINTECH | India | NSE | Financials > Financial Services > Capital Markets > Asset-Servicing Technology | EC | SR, GR | MID | M4 | COM | NV | REG, EVT, LIQ
NSE:BHARTIARTL | India | NSE | Communication Services > Telecommunication Services > Diversified Telecom > Wireless Services | BC | SR, QC | MEGA | M5 | COM | NV | REG, GEO, BETA
NSE:INDUSTOWER | India | NSE | Communication Services > Telecommunication Services > Diversified Telecom > Telecom Infrastructure | IN | SR, VA | LARGE | M6 | COM | NV | REG, LIQ, BETA
NSE:PERSISTENT | India | NSE | Information Technology > Software & Services > IT Services > IT Consulting & Digital Engineering | GR | QC, MO | MID | M4 | COM | HV | BETA, EVT, GEO
NSE:OFSS | India | NSE | Information Technology > Software & Services > Software > Application Software | VA | QC, SR | LARGE | M5 | COM | NV | LIQ, EVT, REG
NSE:RELIANCE | India | NSE | Energy > Energy > Oil, Gas & Consumable Fuels > Integrated Oil & Gas | BC | SR, VA | MEGA | M6 | COM | NV | CMD, GEO, REG
NSE:LT | India | NSE | Industrials > Capital Goods > Construction & Engineering > Construction & Engineering | CY | QC, SR | MEGA | M5 | COM | NV | BETA, GEO, CMD
NSE:SUNPHARMA | India | NSE | Health Care > Pharmaceuticals, Biotechnology & Life Sciences > Pharmaceuticals > Pharmaceuticals | DF | QC, GR | LARGE | M5 | COM | LV | REG, GEO, EVT
NSE:WABAG | India | NSE | Industrials > Commercial & Professional Services > Commercial Services & Supplies > Environmental Services | EC | SR, GR | SMALL | M4 | COM | HV | LIQ, GEO, EVT
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
| NSE:HDFCBANK | FULL HOUSE | HOUSE | QUATERNARY CONSUMER | VERY LONG | QUEEN → QUEEN | 70% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:POWERGRID | FULL HOUSE | HOUSE | QUATERNARY CONSUMER | VERY LONG | ROOK → ROOK | 80% | Level 7 | 9/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:SHRIRAMFIN | FULL HOUSE | PLAYER | SECONDARY CONSUMER | LONG | ROOK → QUEEN | 65% | Level 6 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:INDIAMART | STRAIGHT | TABLE | TERTIARY CONSUMER | LONG | BISHOP → QUEEN | 60% | Level 5 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:MCX | OVERPLAYED HAND | HOUSE | QUATERNARY CONSUMER | VERY LONG | ROOK → QUEEN | 55% | Level 7 | 9/10 | HIGH | STRUCTURAL PATTERN; analogy not used |
| NSE:KFINTECH | STRAIGHT | DEALER | TERTIARY CONSUMER | VERY LONG | BISHOP → ROOK | 70% | Level 6 | 7/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:BHARTIARTL | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:INDUSTOWER | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | ROOK → ROOK | 60% | Level 6 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:PERSISTENT | FULL HOUSE | DEALER | SECONDARY CONSUMER | LONG | BISHOP → ROOK | 55% | Level 6 | 7/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:OFSS | FULL HOUSE | DEALER | TERTIARY CONSUMER | VERY LONG | BISHOP → ROOK | 55% | Level 6 | 8/10 | MODERATE | STRUCTURAL PATTERN; analogy not used |
| NSE:RELIANCE | FULL HOUSE | TABLE | PRODUCER | VERY LONG | ROOK → QUEEN | 65% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:LT | FULL HOUSE | DEALER | SECONDARY CONSUMER | LONG | ROOK → QUEEN | 55% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:SUNPHARMA | FULL HOUSE | PLAYER | PRODUCER | LONG | BISHOP → ROOK | 55% | Level 7 | 8/10 | ELEVATED | STRUCTURAL PATTERN; analogy not used |
| NSE:WABAG | STRAIGHT | PLAYER | SECONDARY CONSUMER | LONG | BISHOP → ROOK | 60% | Level 5 | 6/10 | HIGH | STRUCTURAL PATTERN; analogy not used |
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

## 5. Top 15 India Primary Candidates

| Rank | Company | Ticker | Sector | Primary Use Case | Market Cap | Current Price | MVP Score | Confidence | Casino Role | Chess Piece | Poker Hand | Half-Life | Sovereignty | Mines Risk | Valuation | Entry | Catalyst | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ICICI Bank | NSE:ICICIBANK | Financials | QC | MEGA | ₹1,437.10 | 86 | 89 | HOUSE | QUEEN → QUEEN | FULL HOUSE | VERY LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q1 result on 18 July: deposits, NIM and asset quality | Deposit competition, NIM compression and renewed slippage | STRUCTURAL COMPOUNDER |
| 2 | HDFC Bank | NSE:HDFCBANK | Financials | VA | MEGA | ₹819.15 | 84 | 88 | HOUSE | QUEEN → QUEEN | FULL HOUSE | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | WAIT FOR CATALYST | Confirmed Q1 result on 18 July | Post-merger NIM, deposit mix and ROA drag | WAIT FOR CATALYST |
| 3 | Power Grid Corporation of India | NSE:POWERGRID | Utilities | SR | LARGE | ₹283.25 | 82 | 86 | HOUSE | ROOK → ROOK | FULL HOUSE | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Project capitalization and renewable evacuation awards | Leverage, commissioning delay and allowed-return changes | STRUCTURAL COMPOUNDER |
| 4 | Shriram Finance | NSE:SHRIRAMFIN | Financials | GR | LARGE | ₹1,028.90 | 82 | 88 | PLAYER | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Funding-cost and credit-cost normalization | Used-vehicle/MSME asset quality and liability costs | HIGH-CONVICTION RESEARCH CANDIDATE |
| 5 | IndiaMART InterMESH | NSE:INDIAMART | Communication Services | EC | MID | ₹1,909.20 | 82 | 84 | TABLE | BISHOP → QUEEN | STRAIGHT | LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR CATALYST | Paying-supplier and Busy workflow stabilization | Supplier stagnation, churn and weak reinvestment conversion | WAIT FOR CATALYST |
| 6 | Multi Commodity Exchange of India | NSE:MCX | Financials | SR | MID | ₹2,781.20 | 81 | 84 | HOUSE | ROOK → QUEEN | OVERPLAYED HAND | VERY LONG | 9/10 | 6/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | Q1 volume and revenue-per-contract normalization | Rule shock, premium-turnover loss, regulation and NSE competition | WAIT FOR CATALYST |
| 7 | KFin Technologies | NSE:KFINTECH | Financials | EC | MID | ₹889.00 | 81 | 84 | DEALER | BISHOP → ROOK | STRAIGHT | VERY LONG | 7/10 | 5/10 | FAIRLY VALUED | WAIT FOR CATALYST | Organic international growth and clean integrations | Fee regulation, integration and platform/security failure | EARLY CAPTURE |
| 8 | Bharti Airtel | NSE:BHARTIARTL | Communication Services | BC | MEGA | ₹1,912.50 | 80 | 86 | DEALER | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | BUY-RESEARCH ZONE | ARPU growth and capex moderation | Spectrum liabilities, regulation and Africa currency exposure | STRUCTURAL COMPOUNDER |
| 9 | Indus Towers | NSE:INDUSTOWER | Communication Services | IN | LARGE | ₹404.50 | 80 | 86 | DEALER | ROOK → ROOK | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Tenancy, 5G loading and cash return | Tenant concentration, lease-adjusted leverage and overseas allocation | STRUCTURAL COMPOUNDER |
| 10 | Persistent Systems | NSE:PERSISTENT | Information Technology | GR | MID | ₹5,133.40 | 80 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 7/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR CATALYST | Confirmed Q1 board/results on 21–22 July | US spending, pricing pressure and multiple compression | WAIT FOR CATALYST |
| 11 | Oracle Financial Services Software | NSE:OFSS | Information Technology | VA | LARGE | ₹11,622.00 | 79 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | VERY LONG | 8/10 | 4/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | License/cloud conversion and product refresh | Oracle-parent dependence, low float and license lumpiness | WAIT FOR PULLBACK |
| 12 | Reliance Industries | NSE:RELIANCE | Energy | BC | MEGA | ₹1,320.70 | 79 | 88 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR CATALYST | Confirmed Q1 result on 17 July and digital/retail mix | Capex, O2C cycle, leverage and conglomerate complexity | WAIT FOR CATALYST |
| 13 | Larsen & Toubro | NSE:LT | Industrials | CY | MEGA | ₹3,814.00 | 78 | 87 | DEALER | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | FAIRLY VALUED | BUY-RESEARCH ZONE | ₹7.40T order-book conversion | Project mix, West Asia exposure and working-capital reversal | HIGH-CONVICTION RESEARCH CANDIDATE |
| 14 | Sun Pharmaceutical Industries | NSE:SUNPHARMA | Health Care | DF | LARGE | ₹1,942.80 | 78 | 86 | PLAYER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 5/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | Innovative-medicines growth and Organon integration | FDA action, R&D productivity and acquisition execution | WAIT FOR PULLBACK |
| 15 | VA Tech Wabag | NSE:WABAG | Industrials | EC | SMALL | ₹1,983.30 | 77 | 86 | PLAYER | BISHOP → ROOK | STRAIGHT | LONG | 6/10 | 6/10 | FAIRLY VALUED | WAIT FOR PULLBACK | Framework conversion and higher recurring O&M mix | EPC execution, receivables, country risk and extended entry | EARLY CAPTURE |

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
| 1 | Intercontinental Exchange | NYSE:ICE | Financials | SR | LARGE | $141.76 | 89 | 90 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q2 result on 30 July | Debt, mortgage cycle, data/capture pressure and regulation | STRUCTURAL COMPOUNDER |
| 2 | CME Group | Nasdaq:CME | Financials | IN | LARGE | $246.27 | 88 | 91 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q2 result on 22 July | ADV, market share and revenue-per-contract normalization | STRUCTURAL COMPOUNDER |
| 3 | Adobe | Nasdaq:ADBE | Information Technology | VA | LARGE | $235.31 | 87 | 89 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | UNDERVALUED | WAIT FOR CATALYST | AI-first ARR conversion and permanent CFO succession | AI displacement, ARR deceleration and interim-CFO governance | WAIT FOR CATALYST |
| 4 | Tradeweb Markets | Nasdaq:TW | Financials | GR | LARGE | $101.19 | 87 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 4/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q2 result on 30 July | Fixed-income market share and capture-rate pressure | STRUCTURAL COMPOUNDER |
| 5 | Uber Technologies | NYSE:UBER | Industrials | GR | LARGE | $74.04 | 87 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q2 on 5 August; AV and FCF conversion | Regulation, insurance costs and AV-platform bypass | HIGH-CONVICTION RESEARCH CANDIDATE |
| 6 | McKesson | NYSE:MCK | Health Care | QC | LARGE | $841.31 | 87 | 91 | DEALER | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed FY27 Q1 on 5 August | CVS/top-ten customer concentration, policy and opioid liabilities | STRUCTURAL COMPOUNDER |
| 7 | BlackRock | NYSE:BLK | Financials | BC | LARGE | $1,087.05 | 86 | 94 | TABLE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 8/10 | 5/10 | ATTRACTIVE | WAIT FOR PULLBACK | HPS/private-markets integration and Aladdin ACV | Market beta, integration and transaction-related dilution | WAIT FOR PULLBACK |
| 8 | CACI International | NYSE:CACI | Industrials | VA | MID | $462.85 | 86 | 89 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 4/10 | UNDERVALUED | BUY-RESEARCH ZONE | Confirmed FY26/FY27 guide on 5 August | Federal timing, customer concentration and ARKA leverage | HIGH-CONVICTION RESEARCH CANDIDATE |
| 9 | BNY | NYSE:BNY | Financials | DF | LARGE | $160.86 | 85 | 95 | HOUSE | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 3/10 | FAIRLY VALUED | WAIT FOR PULLBACK | Fee-led platform leverage and collateral growth | Post-result gap, rate normalization, fee regulation and cyber concentration | WAIT FOR PULLBACK |
| 10 | Visa | NYSE:V | Financials | BC | MEGA | $365.14 | 85 | 92 | CHIP | QUEEN → QUEEN | STRAIGHT FLUSH | VERY LONG | 9/10 | 4/10 | EXPENSIVE BUT DEFENSIBLE | WAIT FOR PULLBACK | Confirmed fiscal Q3 on 28 July | Regulation, litigation, valuation and alternative payment rails | WAIT FOR PULLBACK |
| 11 | Copart | Nasdaq:CPRT | Industrials | QC | LARGE | $28.29 | 84 | 88 | HOUSE | ROOK → QUEEN | FULL HOUSE | VERY LONG | 9/10 | 4/10 | ATTRACTIVE | WAIT FOR CATALYST | Unit and pricing stabilization | Insurer volume weakness and falling returns on land investment | WAIT FOR CATALYST |
| 12 | Toast | NYSE:TOST | Financials | EC | LARGE | $30.33 | 83 | 87 | CHIP | BISHOP → QUEEN | STRAIGHT | LONG | 7/10 | 5/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Retail, international, payroll and non-payment attach | Restaurant cycle, competition, SBC and dilution | EARLY CAPTURE |
| 13 | Veralto | NYSE:VLTO | Industrials | DF | LARGE | $94.21 | 82 | 88 | DEALER | ROOK → ROOK | FULL HOUSE | LONG | 9/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Confirmed Q2 call on 29 July | Organic softness, tariffs and M&A execution | STRUCTURAL COMPOUNDER |
| 14 | Veeva Systems | NYSE:VEEV | Health Care | GR | LARGE | $197.37 | 82 | 90 | TABLE | ROOK → QUEEN | FULL HOUSE | LONG | 8/10 | 4/10 | ATTRACTIVE | WAIT FOR CATALYST | Vault CRM, Data Cloud and AI-agent adoption | CRM transition, pharma budgets and SBC | WAIT FOR CATALYST |
| 15 | MSA Safety | NYSE:MSA | Industrials | QC | MID | $173.39 | 82 | 88 | DEALER | BISHOP → ROOK | FULL HOUSE | LONG | 8/10 | 3/10 | ATTRACTIVE | BUY-RESEARCH ZONE | Autronica integration and margin conversion | Industrial cycle, tariffs and acquisition execution | STRUCTURAL COMPOUNDER |

### United States candidate theses and invalidations

1. **ICE — WHY IT REMAINS:** Q1 net revenue rose 20% to $3.0B, operating margin was 56%, adjusted margin 65% and Q1 FCF about $1.15B. Clearing, energy/rates markets, fixed-income data and mortgage workflow are independent made edges. Invalidate on data slowdown, exchange share/capture loss or failed deleveraging. [Official Q1](https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-Reports-Record-First-Quarter-2026/default.aspx)

2. **CME — WHY IT REMAINS:** Q1 revenue rose 14% to $1.9B with a 72.8% adjusted operating margin and $3.36 adjusted EPS. Operating cash flow was $1,259.9M and capex $21.8M, implying conventional FCF near $1,238.1M; cash including FICC was $2.6B versus $3.4B debt. Proprietary liquidity, margin offsets and clearing earn regardless of market direction. Invalidate on persistent ADV/share loss, capture deterioration or adverse rule changes. [Official Q1](https://www.cmegroup.com/media-room/press-releases/2026/4/22/cme_group_inc_reportsrecordrevenueadjustedoperatingincomeadjuste.html)

3. **Adobe — WHY IT REMAINS, WITH A GOVERNANCE DISCOUNT:** FQ2 revenue was $6.62B (+13%), operating cash flow $2.17B and AI-first ARR exceeded $500M. At $235.31, official FY26 guidance implies about **13.1x GAAP EPS** or **9.6x non-GAAP EPS**, not the lower unlabeled provider multiple sometimes shown. The market prices severe disruption, but CFO Dan Durn's departure and interim-CFO transition are real mines. Invalidate on ARR deceleration, margin damage or AI products failing to preserve retention/pricing. [Official FQ2 release and guidance](https://www.adobe.com/cc-shared/assets/investor-relations/pdfs/11606202/a5543arefgt.pdf)

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

15. **MSA Safety — WHY IT REMAINS:** Q1 sales were $463.6M (+10% GAAP, +3% organic), operating income $93.0M at 20.1%, net income $71.3M and FCF $65.1M (91% conversion). Cash was $180.2M against $613.1M current and long-term debt, or $433M net debt and 0.9x net leverage, with $1.2B liquidity. At $173.39 the quote is roughly 28.4x provider TTM FCF—reasonable only if standards economics and Autronica integration sustain growth. Invalidate on organic contraction, margin below 18% or acquisition leverage/returns disappointing. [Official Q1 release](https://investors.msasafety.com/news-releases/news-release-details/msa-safety-announces-first-quarter-2026-results)

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

## 9. Current Houses, Tables, Chips, and Rails

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

## 10. Combined India + US Top 20

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

## 11. Best Risk-Adjusted Ideas

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

## 15. Final Daily Synthesis

| No. | Required Selection | Winner | Why | What Market May Be Missing | Catalyst | Invalidation | Evidence Needed Next |
|---|---|---|---|---|---|---|---|
| 1 | Best India opportunity today | ICICI Bank (NSE:ICICIBANK) | Highest India blend of capital, underwriting, customer ownership and pot odds. | Quality can persist without a heroic rate or credit assumption. | Q1 deposits, NIM and slippage. | NIM persistently below 4%, deposits lag loans, or renewed slippage. | Fresh Q1 capital, deposit, NPA and restructured-book bridge. |
| 2 | Best US opportunity today | Intercontinental Exchange (NYSE:ICE) | Best overall score and broadest diversified House at a defensible valuation. | Mortgage weakness obscures clearing, energy/rates, data and workflow compounding. | Confirmed Q2 on 30 July. | Data slowdown, share/capture loss or deleveraging failure. | Segment organic growth, mortgage revenue, FCF and net-debt bridge. |
| 3 | Best India early-capture opportunity | KFin Technologies (NSE:KFINTECH) | Converted international growth, positive FCF and a credible Dealer-to-Table path. | Exportable asset-servicing technology, not merely a domestic registrar. | Organic international growth and integration updates. | Organic growth below 15%, margin below 38%, or weaker retention. | Acquisition-separated growth, retention, margin and diluted FCF/share. |
| 4 | Best US early-capture opportunity | Toast (NYSE:TOST) | ARR, location and GPV growth now coexist with positive FCF. | Retail, international, payroll and capital attach can widen value per location. | Next result and attach-rate disclosure. | Location/GPV growth below mid-teens or SBC blocks per-share conversion. | Cohort retention, recurring gross profit, SBC/share and international economics. |
| 5 | Best India structural house/table/rail | Power Grid Corporation of India (NSE:POWERGRID) | An unavoidable regulated transmission rail earns across competing generation winners. | Renewable evacuation converts capex into regulated assets rather than a directional power bet. | Project capitalization and awards. | Allowed-return damage, commissioning delay or debt outruns earnings. | Project capitalization, CWIP, leverage and regulated-return schedule. |
| 6 | Best US structural house/table/rail | Intercontinental Exchange (NYSE:ICE) | Clearing permission, proprietary liquidity, data and workflow form the broadest House. | Four reinforcing rails make earnings less volume-dependent than the exchange label implies. | Confirmed Q2 on 30 July. | Regulatory economics change or recurring data loses pricing/share. | Data retention, clearing share, mortgage workflow and leverage. |
| 7 | Best India risk-adjusted opportunity | ICICI Bank (NSE:ICICIBANK) | Highest combination of sovereignty, evidence, valuation and mine survival. | The balance sheet does not require a repair thesis. | Q1 deposit/NIM evidence. | Deposit franchise weakens or credit cost rises sharply. | Deposit cohorts, LCR, CET1, credit cost and segment ROA. |
| 8 | Best US risk-adjusted opportunity | CME Group (Nasdaq:CME) | Benchmark liquidity, clearing and exceptional margins with low mine density. | Product depth and collateral efficiency can compound without permanently higher volatility. | Confirmed Q2 on 22 July. | Persistent ADV/share loss or capture deterioration. | Product ADV, open interest, capture, expenses and capital return. |
| 9 | Highest-upside India candidate | Kaynes Technology (NSE:KAYNES) | Successful OSAT/critical-electronics promotion could change both role and addressable market. | Platform value is possible only after qualification and utilization—not yet made. | Customer qualification and capex commissioning. | Funding stress, delay, low utilization or persistent negative post-capex FCF. | Binding customers, yields, utilization, funding stack and audited FCF bridge. |
| 10 | Highest-upside US candidate | AST SpaceMobile (Nasdaq:ASTS) | Direct-to-device service could become a global telecom layer. | Partner distribution may lower customer-acquisition needs if the constellation works. | Funding terms, launch cadence and first recurring commercial revenue. | Launch/technical failure, underfunding or dilution overwhelms per-share value. | Final financing, uptime, service revenue and funded deployment. |
| 11 | Most attractively valued India candidate | HDFC Bank (NSE:HDFCBANK) | Post-merger valuation discounts weaker economics despite exceptional deposits and capital. | ROA/NIM normalization may be closer than sentiment assumes. | Confirmed Q1 on 18 July. | NIM below 3.3%, deposits disappoint or merger drag persists. | Average-balance NIM, deposit mix, ROA, costs and asset quality. |
| 12 | Most attractively valued US candidate | Adobe (Nasdaq:ADBE) | Low official-guidance earnings pot odds with substantial cash generation. | AI can be an upsell and retention tool, not only a substitute. | AI ARR, retention and permanent CFO succession. | ARR deceleration, margin damage or AI erodes pricing/retention. | Product AI ARR, renewal cohorts, inference cost, SBC and FCF. |
| 13 | Most overpriced pawn | IonQ (NYSE:IONQ) | Commercial cash evidence remains tiny relative to a valuation assuming scaled quantum demand. | Technical progress is not yet repeatable cash-generating standard control. | Commercial revenue and error-correction evidence. | Scaled customer use and positive unit economics arrive much sooner than expected. | Production workloads, bookings conversion, burn and dilution. |
| 14 | Best matrix segment winner overall | Intercontinental Exchange (NYSE:ICE) | It wins Structural Rail, House, Very-Long Half-Life and overall score without heroic entry assumptions. | The combined ecosystem is broader than the exchange label. | Confirmed Q2 on 30 July. | Multi-segment organic growth or cash conversion weakens materially. | Segment revenue, recurring data, clearing share, FCF and debt. |
| 15 | Best under-followed India discovery | Shriram Finance (NSE:SHRIRAMFIN) | Mid-teens AUM growth and normalized profit growth at attractive pot odds. | The franchise may be evolving beyond specialist vehicle lending. | Funding-cost and credit-cost normalization. | Stage 2/3 rises, collections weaken or funding advantage disappears. | Vintages, collections, Stage 2/3, ECL and ALM schedule. |
| 16 | Best under-followed US discovery | BNY (NYSE:BNY) | Fresh fee growth, platform margin and 31.3% ROTCE show converted operating leverage. | It remains framed as a rate-sensitive custodian rather than settlement/collateral infrastructure. | Fee-led growth after the result gap. | Fee/margin reversal, CET1 pressure or a major cyber event. | Organic fee/NII bridge, platform expenses, CET1 and buybacks. |

### 17. Top 10 companies requiring immediate deeper research

| Priority | Company | Why immediate | What the market may be missing | Main catalyst | Invalidation | Evidence required next |
|---:|---|---|---|---|---|---|
| 1 | HDFC Bank | Q1 is one day away and can resolve the post-merger normalization debate | Average-balance economics may improve faster than reported-period sentiment | 18 July result | Weak deposits, sub-3.3% NIM or no ROA progress | Full Q1 deck, average balances, deposit mix and management bridge |
| 2 | CME Group | High-quality house with a confirmed result inside one week | Product breadth and collateral efficiency may offset ADV normalization | 22 July result | Share/capture loss or expense surprise | ADV/open-interest by product, capture and guidance |
| 3 | KFin Technologies | Best India promotion geometry with integration complexity | Organic international servicing could become the independent ceiling | Next organic/integration disclosure | Acquisition-only growth or margin/retention slippage | Organic/constant-currency growth, churn, margin and FCF/share |
| 4 | VA Tech Wabag | New water-rail candidate with ₹17,200+ crore order book and net cash | Recurring O&M and technology economics may be hidden by EPC classification | Framework conversion and quarterly collections | Receivable stress or order conversion stalls | Customer/order aging, cash collections, O&M share and post-WC FCF |
| 5 | Shriram Finance | Fresh quality/value candidate needs credit-vintage verification | Diversification may reduce the historical specialist-lender discount | Quarterly credit/funding update | Stage 2/3 or cost of funds rises materially | Vintages, collections, Stage 2/3, ECL and ALM schedule |
| 6 | BNY | Fresh Q2 operating evidence is excellent but the stock gapped 5.1% | Platform operating leverage may be durable beyond rate support | Post-result follow-through and next monthly/quarterly data | Fee/margin reversal or capital pressure | Organic fee bridge, NII sensitivity, CET1 and technical gap support |
| 7 | Adobe | Valuation says structural impairment while AI ARR says partial conversion | AI can be an upsell and retention tool, not only a substitute | Next AI ARR update and CFO appointment | Net-new ARR/retention weakens or margins fall | Cohort retention, product attach, inference cost, SBC and FCF |
| 8 | Reliance Industries | Q1 board meeting is today and can reprice the digital/retail/O2C mix | Digital and retail cash conversion may be masked by conglomerate and O2C volatility | 17 July Q1 result and analyst meet | Net debt rises, consumer segment margins weaken or new-energy capex lacks conversion | Segment EBITDA, capex, net debt, Jio/retail KPIs and post-capex cash flow |
| 9 | Copart | High-sovereignty marketplace is in a unit-growth pause | Yard density and global buyer liquidity can compound even before units recover | Unit/pricing stabilization | Units stay weak without price/share gains or land ROIC falls | Units, revenue per unit, insurer share, capex and land returns |
| 10 | Indus Towers | New value-backed rail with conventional FCF and net cash excluding leases, tempered by lease-inclusive net debt | Traffic/loading and overseas reuse can extend the cash runway | Tenancy/loading and capital-return update | Vodafone Idea collections fail, lease-adjusted leverage worsens or overseas capex destroys ROIC | Tenant receivables, tower/colocation adds, loading, lease liabilities, capex and payout policy |

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

The daily answer is the overlap of control, cash conversion, sovereignty, reasonable pot odds and survivable mines—not the loudest multiplier. Today that favors **ICE, CME, ICICI Bank, Power Grid, McKesson and CACI**; the cleaner earlier-capture paths are **KFin, Toast, Shriram Finance and Wabag**.

`MATRIX WINNER DISCOVERY COMPLETE`
