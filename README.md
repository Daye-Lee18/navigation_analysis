# Navigation Analysis — Hyundai AutoEver 2026 Task Test

A data-driven investigation into two real navigation complaints (VOCs) using Seoul traffic data, road-link geometry, and live incident APIs.

---

## Background

Two customer complaints were given as the starting point:

| # | Complaint | Scenario |
|---|-----------|----------|
| **VOC1** | ETA was too optimistic | Navigation predicted 60 min; trip took 80 min (+30% overrun) |
| **VOC2** | Navigation suggested an unnecessary detour | App avoided a direct 10 km route and recommended a 30 km detour instead |

The goal was to reproduce each complaint with real data, identify root causes through structured hypothesis testing, and propose concrete improvements.

---

## What I Did

### Data

| Dataset | Source | Scale |
|---------|--------|-------|
| Seoul vehicle speed (March 2026) | TOPIS | 5,080 links × 31 days × 24 hours (~3.77 M rows) |
| Seoul traffic volume (February 2026) | TOPIS | Hourly counts with GPS coordinates (~160 K rows) |
| National standard node-link (navigation_db) | MOLIT | 63,288 Seoul links with geometry and speed limits |
| Real-time incident info (AccInfo API) | Seoul Open Data Plaza | Live accidents, construction, road closures |

### Analysis approach

Both VOCs were broken down into testable hypotheses and validated against the datasets above.

#### VOC1 — ETA Error Analysis (`voc1_analysis.py`)

| Hypothesis | Question |
|------------|----------|
| **H1** — Intersection delay not modelled | Do speeds drop sharply at peak hours on corridor links? |
| **H2** — Stale traffic data | Does day-to-day speed variance make yesterday's average a bad predictor? |
| **H3** — Incident not reflected in ETA | Was there a real incident on the affected road during the peak window? |
| **H4** — Mean-based ETA underestimates variance | How often does peak-hour speed fall below the 30%-overrun threshold? |

**Key findings:**

- **Error localisation (H0):** Olympic Expressway (link 1150006000/6500) had the worst ETA overrun at **+352%** during the 7–9 AM peak. The worst links all cluster on arterial corridors entering the city centre.
- **H1 confirmed:** Speed on the top-10 error links drops from 71.9 km/h at 06:00 to 32.6 km/h by 09:00 — a **45.5% collapse** that a mean-based ETA cannot anticipate.
- **H2 confirmed:** The Olympic Expressway day-to-day coefficient of variation (CV) at 8 AM is **0.66** — yesterday's average is essentially useless as a point estimate.
- **H3 confirmed:** A vehicle breakdown on the Olympic Expressway was recorded in `navigation_db.acc_info_history` at **07:31, lasting 55 minutes through peak hour** — directly matching the highest-error road from H0.
- **H4 confirmed:** Across all 3,611 peak-hour links, CV = 0.52 and **12.6% of link-hours exceed 30% ETA error**, proving a single mean value is structurally inadequate for high-variance peak conditions.

#### VOC2 — Detour Route Analysis (`voc2_analysis.py`)

Two competing routes were constructed from real data:

| Route | Road | Distance | Characteristics |
|-------|------|----------|-----------------|
| **Route A** (direct) | Olympic Expressway | 18.5 km | Urban motorway — fast but volatile |
| **Route B** (detour) | Dongil-ro · Cheonho-daero | 18.3 km | Arterial — slow but stable |

Route A is faster in every time slot under normal conditions. The question was: what causes the navigation to prefer Route B?

| Hypothesis | Finding |
|------------|---------|
| **H1** — Speed over-estimation | Route A must be underestimated by **≥33%** for Route B to win on cost. This actually happened on **10 of 31 days (32%)** in March — on those days, the detour was justified. |
| **H2** — Stale road restriction (**most likely root cause**) | If a closure on Route A was cleared but the navigation DB was not yet updated, the system avoids a passable road. The AccInfo `exp_clr_date` lag mechanism directly explains persistent detours on the other 21 days. |
| **H3** — Cost function bias | With only 0.2 km distance difference between the two routes, the distance weight β would need to be 55.52 min/km to flip the cost — unrealistic. However, in the original 10 km vs 30 km scenario, a small β **is** enough to cause the issue. |
| **H4** — Re-routing trigger too sensitive | Route A's 8 AM speed std dev is ±24.2 km/h. A simple speed threshold triggers re-routing during temporary congestion, locking the user into Route B even after congestion clears. |

---

## Results

### Output files

| File | What it shows |
|------|---------------|
| `output/h0_eta_error_by_link.png` | ETA overrun rate by link — top error corridors highlighted |
| `output/h1_peak_speed_drop.png` | Hour-by-hour speed collapse on highest-error links |
| `output/h2_weekday_variance.png` | Day-to-day speed variance per link during peak hours |
| `output/h3_accinfo_db.json` | Incident records pulled from PostgreSQL (AccInfo history) |
| `output/h3_accinfo_peak_speed.png` | Incident timeline overlaid on peak-hour speed data |
| `output/h4_speed_distribution.png` | Speed distribution + CV across all peak links |
| `output/voc1_map.html` | Interactive map — ETA error rates on Seoul road network |
| `output/voc2_h1_cost_function.png` | Cost-function breakeven — speed threshold for route flip |
| `output/voc2_h1_daily_speed.png` | Daily Route A vs Route B speed comparison (March) |
| `output/voc2_h2_road_restriction.json` | Road restriction event summary from AccInfo |
| `output/voc2_h3_cost_sensitivity.png` | Cost sensitivity to distance weight β |
| `output/voc2_h4_rerouting.png` | Re-routing trigger analysis — threshold sensitivity |
| `output/voc2_map.html` | Interactive map — Route A vs Route B on Seoul road network |

### Reports

- `solution_file/VOC1_ETA_분석_보고서.md`
- `solution_file/VOC2_이상경로_분석_보고서.md`
- `solution_file/20260406_현대오토에버과제테스트.pdf`

---

## Root Cause Summary

### VOC1 — Why ETA was wrong

```
Primary:   Intersection delay not separately modelled
           → travel time is link-sum only; signal wait not included

Secondary: ETA model uses historical mean speed
           → cannot react to same-day congestion spikes, incidents, or high-variance days

Result:    Peak-hour ETA underestimated by 30%+ on 12.6% of link-hours
```

### VOC2 — Why the detour was chosen

```
Direct cause 1:  Stale road restriction in navigation DB (H2)
                 → cleared closure kept Route A marked as blocked

Direct cause 2:  Re-routing trigger too sensitive (H4)
                 → temporary slowdown on Route A → reroute fired → user stuck on Route B

Indirect:        Speed underestimation (H1) on 32% of days, cost-function β too small (H3)
```

---

## Future Work

### Short-term (data / algorithm)

| Item | Detail |
|------|--------|
| Model intersection delay separately | Add signal-cycle-based wait time on top of link travel time |
| Display ETA confidence interval | Show "60–75 min" instead of a single point estimate |
| Strengthen real-time AccInfo integration | Trigger re-routing immediately on incident registration |
| Reduce AccInfo DB update lag | Push closure clearance to navigation DB in near-real-time |
| Compound re-routing condition | Require threshold breach to persist for N minutes before firing re-route |

### Medium / long-term (AI models)

| Model | What it solves |
|-------|----------------|
| **LSTM / Transformer** for traffic forecasting | Captures same-day trend shifts — addresses VOC1 H1 & H2 |
| **Intersection delay model** | Learns per-link signal wait time — addresses VOC1 H1 |
| **Ensemble ETA** (rule-based + ML hybrid) | Robust to outliers — addresses VOC1 H4 |
| **Anomaly detection on route speed** | Re-routes only on statistically abnormal drops — addresses VOC2 H4 |
| **ML-based route selection** | Learns optimal route from speed, restrictions, and time-of-day features |
| **Personalised routing** | Adapts to individual driver speed preferences and road affinity |

### Future service vision

- **Uncertainty-aware navigation:** "60 min (±15 min)" — communicate forecast confidence to the user
- **Transparent re-routing:** "Re-routing due to accident on Olympic Expressway" — show the reason
- **User feedback loop:** "Was this route correct?" — collect signal to retrain the model

---

## Limitations

| Limitation | Reason | Mitigation |
|------------|--------|------------|
| No GPS trajectory data | Internal fleet data not available | Use ETRI/T-DATA vehicle trajectory dataset or synthetic data |
| No AccInfo historical records for March | API only exposes currently active events | Run a continuous polling pipeline or purchase archival data |
| Speed data is hourly | Cannot capture minute-level congestion bursts | Collect via TrafficInfo API at higher frequency |
| Incomplete link geometry mapping | Only 1,505 of 5,080 links matched to standard node-link | Complete service-link ↔ standard-link mapping table |
| Cost function parameters undisclosed | Internal navigation system | Back-calculate from route choice logs or obtain from internal docs |

---

## How to reproduce

```bash
# 1. Prepare processed datasets
python data_prep.py

# 2. Run VOC1 analysis
python voc1_analysis.py

# 3. Run VOC2 analysis
python voc2_analysis.py

# 4. Open interactive maps
open output/voc1_map.html
open output/voc2_map.html
```

### Dependencies

- Python 3.10 (Anaconda)
- `pandas`, `geopandas`, `folium`, `matplotlib`, `shapely`, `psycopg2`
- PostgreSQL (`navigation_db`) with Seoul node-link data loaded
- `.env` with API keys for AccInfo and TrafficInfo services

---

*Analysis date: 2026-04-07*
