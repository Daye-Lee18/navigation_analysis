# Hyundai AutoEver Interview Prep
**현대오토에버 Navigation Data Scientist — 면접 대비 스크립트**

---

## HOW TO USE THIS FILE

Each section has:
- **The question** the interviewer is likely to ask
- **Your answer script** — written in the voice you'd actually speak
- **Key numbers to memorize** — the data points that make you credible

---

## PART 1 — THE TASK TEST (과제 설명)

---

### Q1. 과제 테스트를 간단히 소개해 주세요.

**Script:**
> "현대오토에버 내비게이션 서비스에서 접수된 실제 고객 불만(VOC) 2건을 데이터로 재현하고 원인을 분석하는 과제였습니다.
>
> VOC1은 ETA가 60분이라 했는데 80분이 걸린 케이스였고,
> VOC2는 평소 10km 직진 경로 대신 30km 우회로를 안내한 케이스였습니다.
>
> 저는 서울시 TOPIS 차량 통행속도 데이터 약 377만 행, 교통량 데이터, 국토부 전국표준노드링크, 그리고 서울 열린데이터광장의 실시간 돌발정보 API를 PostgreSQL에 적재하고, 각 VOC별로 가설을 세워 데이터로 검증하는 방식으로 분석했습니다."

**Key numbers:**
- 5,080 links × 31 days × 24 hours = 3.77M rows (TOPIS speed data)
- 63,288 Seoul links in navigation_db
- 2 VOCs → 4 hypotheses each → all confirmed with real data

---

### Q2. 어떤 데이터를 어떻게 수집하고 준비했나요?

**Script:**
> "크게 세 가지 소스를 썼습니다.
>
> 첫째, TOPIS에서 2026년 3월 서울시 차량통행속도 파일을 다운받아 PostgreSQL에 적재했습니다. 링크별·시간별 평균 속도(km/h)가 담겨 있어 ETA 오차 계산의 핵심 데이터였습니다.
>
> 둘째, 국토부 전국표준노드링크 SHP 파일을 shp2pgsql로 PostgreSQL에 올려 링크 geometry와 제한속도를 갖는 navigation_db를 구성했습니다.
>
> 셋째, 서울 열린데이터광장의 AccInfo API와 TrafficInfo API를 Python으로 폴링해 실시간 돌발 이벤트 이력을 수집했습니다.
>
> 데이터 준비 시 가장 까다로웠던 부분은 서비스링크 ID와 표준노드링크 ID가 달라서 JOIN이 안 되는 문제였습니다. 5,080개 중 1,505개만 geometry 매핑이 되었고, 이 부분은 한계로 명시했습니다."

**Key numbers:**
- Link ID mismatch: 5,080 service links, only 1,505 mapped to standard node-link
- API polling interval: ~5 minutes for AccInfo
- Tools: pandas, geopandas, folium, psycopg2, shapely, PostgreSQL, DBeaver, Tableau

---

## PART 2 — ROUTE PLANNING ALGORITHM (경로 추천 알고리즘)

---

### Q3. Dijkstra와 A* 알고리즘의 차이를 설명해 주세요.

**Script:**
> "두 알고리즘 모두 최단 경로를 찾는 그래프 탐색 알고리즘인데, 핵심 차이는 탐색 방향입니다.
>
> Dijkstra는 출발 노드에서 가까운 순으로 모든 방향을 균일하게 탐색합니다. 최적해를 반드시 보장하지만, 노드가 많을수록 계산이 느립니다.
>
> A*는 Dijkstra에 heuristic을 추가합니다. 현재 비용(g)에 목적지까지의 추정 비용(h)을 더한 f = g + h로 우선순위를 정해서, 목적지 방향으로 탐색을 집중합니다. heuristic이 실제 비용을 과대추정하지 않는 admissible 조건만 지키면 최적해를 보장하면서 Dijkstra보다 훨씬 빠릅니다.
>
> 내비게이션에서는 A*가 주로 쓰이는데, 서울처럼 수만 개 링크가 있는 도로망에서 Dijkstra로 전체 탐색하면 실시간 경로 계산이 불가능하기 때문입니다. 실제로 제 분석에서도 과제 배경 자료에 '내비게이션은 dijkstra, A* algorithm으로 경로를 추천한다'고 명시되어 있었습니다."

**Follow-up they may ask:**
> "내비게이션 cost function은 어떻게 구성되나요?"

**Script:**
> "기본적으로 `cost = α × 시간 + β × 거리 + γ × 기타` 형태입니다.
>
> 시간 가중치 α가 가장 중요하고, 거리 가중치 β는 불필요하게 긴 경로에 패널티를 줍니다.
>
> 제 VOC2 분석에서 β의 영향을 직접 수치로 계산했는데, 올림픽대로(18.5km) vs 동일로(18.3km)처럼 거리 차이가 0.2km밖에 안 되면 β가 55.52 min/km라는 비현실적인 값이어야만 경로가 역전됩니다. 하지만 원래 VOC 시나리오인 10km vs 30km처럼 거리 차이가 클 경우에는 β 설정이 경로 선택에 직접 영향을 미칩니다."

---

### Q4. 실시간 교통 상황에서 경로 재탐색은 언제 트리거해야 한다고 생각하나요?

**Script:**
> "이게 VOC2의 H4에서 제가 분석한 핵심 문제였습니다.
>
> 현재 내비게이션은 속도가 임계값 아래로 떨어지면 즉시 재탐색을 실행합니다. 문제는 올림픽대로처럼 속도 표준편차가 ±24.2 km/h로 큰 도로에서는, 일시적 혼잡만으로도 재탐색이 발생하고 혼잡이 해소된 후에도 우회로에 고착된다는 겁니다.
>
> 제 개선안은 두 가지입니다.
> 첫째, 단순 속도 임계값이 아니라 '속도가 N분 이상 지속적으로 임계 이하일 때'만 재탐색을 트리거하는 compound 조건을 추가합니다.
> 둘째, AccInfo API의 이벤트 등록 즉시 해당 링크를 포함한 경로를 재탐색하는 event-driven 트리거를 함께 사용합니다.
>
> 이 두 가지를 조합하면 '일시적 혼잡 → 불필요한 우회'는 줄이면서 '실제 사고 → 빠른 재탐색'은 살릴 수 있습니다."

---

## PART 3 — ETA ANALYSIS (VOC1 심화)

---

### Q5. ETA 오차 분석을 어떻게 접근했나요? 핵심 발견을 설명해주세요.

**Script:**
> "먼저 '어디서 오차가 크냐'는 Error Localization(H0)부터 했습니다.
>
> 내비게이션이 링크 전체 평균 속도로 ETA를 예측한다고 가정하고, 실제 피크 시간대 속도와 비교해 ETA 오차율을 계산했습니다. 오차율 공식은 `(실제통행시간 - 예측통행시간) / 예측통행시간`입니다.
>
> 결과적으로 올림픽대로 두 링크에서 오차율이 +352%였습니다. 피크 시간 평균 속도가 21.3 km/h인데 전체 평균은 48.3 km/h니까 ETA가 실제의 절반도 안 되게 예측된 겁니다.
>
> 그 원인으로 4가지 가설을 검증했고, 모두 유력으로 확인됐습니다.
> H1: 6시 71.9 km/h → 9시 32.6 km/h, 피크 진입 시 45.5% 속도 급락 — 교차로 대기 미반영
> H2: 올림픽대로 날짜별 변동계수 CV=0.66 — 어제 데이터로 오늘 예측 불가
> H3: 07:31 올림픽대로 차량고장 이벤트가 AccInfo DB에서 확인 — 55분간 피크와 겹침
> H4: 전체 피크 링크 평균 CV=0.52, 30% 초과 오차 발생 비율 12.6%"

**Key numbers to remember:**
- +352% ETA overrun on Olympic Expressway
- 45.5% speed collapse from 6am to 9am
- CV = 0.66 (Olympic Expressway day-to-day variance)
- CV = 0.52 (all 3,611 peak links)
- 12.6% of link-hours exceed 30% ETA error
- Incident: 07:31, lasted 55 minutes, confirmed in navigation_db.acc_info_history

---

### Q6. ETA를 개선하려면 어떤 AI 모델을 쓰겠습니까?

**Script:**
> "단기와 중장기로 나눠 생각했습니다.
>
> 단기적으로는 알고리즘 개선입니다. 링크 통행시간 합산에 교차로 신호주기 기반 대기시간을 별도로 추가하고, ETA를 단일 값이 아닌 '60~75분' 같은 신뢰구간으로 표시합니다.
>
> 중장기적으로는 LSTM 또는 Transformer 기반 시계열 모델을 쓰겠습니다. 이유는 교통 데이터가 시간 순서 의존성이 강해서 — 7시 속도가 6시 속도의 함수고 어제 패턴이 오늘 초기값에 영향을 미치기 때문입니다. 특히 Transformer의 attention mechanism은 '오늘 6시에 이미 속도가 이 정도면 8시는 얼마다'라는 당일 context를 잘 포착합니다.
>
> 또한 rule-based와 ML을 결합한 ensemble ETA를 만들면 — 데이터가 충분한 일반 상황은 ML, 돌발 이벤트 발생 시는 AccInfo 트리거 기반 rule로 대응하는 hybrid 구조 — 이상치에 강건한 시스템을 만들 수 있습니다.
>
> 궁극적으로는 사용자가 '60분 (±15분)'이라는 불확실성까지 인지할 수 있는 uncertainty-aware navigation을 지향점으로 봤습니다."

---

## PART 4 — DETOUR ROUTE ANALYSIS (VOC2 심화)

---

### Q7. 왜 내비가 더 빠른 경로를 놔두고 30km 우회를 선택했다고 판단했나요?

**Script:**
> "저는 네 가지 가설을 세우고 데이터로 하나씩 검증했습니다.
>
> 가장 유력한 원인은 두 가지입니다.
>
> 첫째, 도로 통제 정보 갱신 lag (H2)입니다. AccInfo API에는 `exp_clr_date`라는 필드가 있는데, 이 날짜가 지났는데도 내비게이션 DB에 통제 정보가 남아있으면 이미 통행 가능한 도로를 계속 회피하게 됩니다. 이 lag 메커니즘이 21일(68%) — H1으로 설명 안 되는 날 — 의 우회를 가장 직접적으로 설명합니다.
>
> 둘째, 재탐색 트리거 과민 (H4)입니다. Route A인 올림픽대로의 표준편차가 ±24.2 km/h로 매우 커서, 일시적 혼잡만으로 재탐색이 발생하고 혼잡 해소 후에도 우회로에 고착됩니다.
>
> 반면 H1 — 속도 과소추정 — 은 31일 중 실제로 속도가 느렸던 10일(32%)만 설명 가능하고, H3 — cost function의 거리 가중치 β — 는 거리 차이가 0.2km뿐인 제 데이터 시나리오에서는 β=55.52라는 비현실적인 값이 필요해 주요 원인이 아닌 것으로 봤습니다."

---

### Q8. Cost function에서 시간과 거리의 가중치를 어떻게 설정해야 한다고 생각하나요?

**Script:**
> "정답은 없고 trade-off의 문제입니다.
>
> 시간 가중치 α를 크게 하면 최소 시간 경로를 선택하는데, 도로 상황이 나쁠 때 매우 긴 우회로라도 빠르면 선택합니다 — 이게 VOC2의 상황입니다. 반면 거리 가중치 β를 키우면 불필요하게 긴 경로에 패널티가 생겨 3배 우회 같은 케이스를 방지할 수 있지만, 진짜로 빠른 우회가 있을 때도 선택하지 않는 부작용이 생깁니다.
>
> 제 분석에서 VOC의 원래 시나리오인 10km vs 30km라면, `β × (30 - 10) = 시간 절감`이므로 β가 상대적으로 작아도 cost 역전이 발생합니다. 즉 β를 살짝만 키워도 3배 우회는 억제할 수 있었을 겁니다.
>
> 이상적으로는 α와 β를 고정값으로 설정하지 않고, 사용자 과거 경로 선택 이력을 학습해 개인화된 가중치를 추론하는 ML 기반 route selection 모델로 발전시키는 게 맞다고 봅니다."

---

## PART 5 — DATA & SQL (기술 역량)

---

### Q9. 이번 과제에서 SQL을 어떻게 활용했나요?

**Script:**
> "PostgreSQL을 내비게이션 데이터 통합 저장소로 사용했습니다.
>
> 주요 쿼리 패턴을 세 가지로 정리하면:
>
> 첫째, ETA 오차 계산입니다. 링크 거리를 속도로 나눠 예측/실제 통행시간을 계산하고, 오차율을 구한 뒤 GROUP BY link_id, 시간대로 집계해 오차가 큰 구간을 특정했습니다.
>
> 둘째, 돌발 이벤트 분석입니다. acc_info_history 테이블에서 occr_time이 피크 시간대(07:00~09:00)에 해당하는 이벤트를 필터링하고, link_id로 traffic_info와 JOIN을 시도했습니다. 여기서 두 API의 link_id 체계가 달라 JOIN이 0건으로 나오는 한계를 발견했고, 이걸 분석 한계로 명시했습니다.
>
> 셋째, 날짜별 속도 분산입니다. STDDEV(speed) / AVG(speed)로 변동계수(CV)를 계산해 H2 가설을 검증했습니다."

**Example SQL they might ask you to write on the spot:**

```sql
-- ETA 오차율 상위 링크 추출
SELECT
    link_id,
    road_name,
    AVG(actual_speed)                          AS avg_actual_speed,
    AVG(predicted_speed)                       AS avg_predicted_speed,
    AVG((predicted_time - actual_time)
        / NULLIF(predicted_time, 0))           AS eta_error_rate
FROM traffic_speed
WHERE hour BETWEEN 7 AND 9
  AND weekday IN ('Mon','Tue','Wed','Thu','Fri')
GROUP BY link_id, road_name
ORDER BY eta_error_rate DESC
LIMIT 10;

-- 날짜별 속도 변동계수 (CV)
SELECT
    link_id,
    AVG(speed)               AS avg_speed,
    STDDEV(speed)            AS stddev_speed,
    STDDEV(speed)
        / NULLIF(AVG(speed), 0) AS cv
FROM traffic_speed
WHERE hour = 8
GROUP BY link_id
ORDER BY cv DESC;
```

---

### Q10. Python 분석 코드에서 어떤 부분이 가장 복잡했나요?

**Script:**
> "두 가지를 꼽겠습니다.
>
> 첫째는 GIS 처리입니다. 국토부 SHP 파일을 geopandas로 읽어 PostgreSQL에 적재하고, 링크 geometry(MultiLineString)를 Folium으로 시각화하는 파트입니다. 특히 좌표계 변환이 까다로웠는데 — 서울시 교통량 데이터가 GRS80 TM 좌표계를 쓰고, 표준 지도는 WGS84를 씁니다. 변환 공식을 미리 확인하지 않으면 좌표가 수백 km 틀어집니다.
>
> 둘째는 API 폴링 파이프라인입니다. AccInfo API가 현재 활성 이벤트만 반환하기 때문에, 이력을 쌓으려면 약 5분 간격으로 폴링해서 acc_info_history 테이블에 upsert하는 파이프라인을 직접 만들어야 했습니다. 중복 없이 새 이벤트만 추가하고 해소된 이벤트를 트래킹하는 로직을 짜는 게 핵심이었습니다."

---

## PART 6 — AI & FUTURE VISION (AI 개선안)

---

### Q11. 내비게이션 서비스에 AI를 적용한다면 어디서부터 시작하겠습니까?

**Script:**
> "우선순위를 세 단계로 나눠 생각했습니다.
>
> 1단계(빠른 효과): ETA 신뢰구간 표시입니다. 모델을 교체하지 않아도, 현재 속도 데이터의 표준편차를 함께 계산해 '60분 (±15분)'으로 표시하면 사용자 경험이 즉시 개선됩니다. CV=0.52인 피크 구간에서 단일 숫자만 주는 건 거짓말에 가깝습니다.
>
> 2단계(핵심 개선): LSTM/Transformer 기반 교통 예측 모델 도입입니다. 1시간 단위 데이터가 아닌 실시간 TrafficInfo API를 분 단위로 수집해 당일 트렌드를 학습하면 H1, H2 문제를 동시에 해결합니다.
>
> 3단계(장기 비전): 사용자 피드백 루프 구축입니다. '이 경로가 맞았나요?'라는 간단한 피드백을 수집하고, 실제 주행 GPS 궤적과 추천 경로를 비교해 모델을 지속적으로 개선하는 사이클을 만드는 겁니다. 제 분석에서 'GPS trajectory 없음'이 가장 큰 한계였는데, 이 피드백 루프가 있으면 그 한계 자체가 사라집니다."

---

### Q12. 이번 분석에서 가장 어려웠던 점은? 그리고 다음에는 어떻게 개선하겠나요?

**Script:**
> "가장 어려웠던 점은 두 API 간 link_id 불일치입니다. AccInfo(돌발 정보)와 TrafficInfo(속도 정보)가 다른 링크 ID 체계를 써서, 사고 발생 링크에서의 속도 변화를 직접 JOIN으로 수치화할 수 없었습니다. H3 가설을 '같은 도로·같은 시간대에 사고와 고속도 저하가 동시에 나타난다'는 방식으로 간접 증명할 수밖에 없었습니다.
>
> 개선 방법은 두 가지입니다.
> 첫째, 서비스링크 ID ↔ 표준링크 ID 매핑 테이블을 완성합니다. 현재 5,080개 중 1,505개만 매핑됐는데, 도로명 + 좌표 근접성(ST_DWithin)을 활용한 fuzzy matching으로 매핑률을 높일 수 있습니다.
> 둘째, AccInfo 폴링 파이프라인을 상시 가동해 3월치 이력 데이터를 충분히 쌓습니다. 현재는 4월 수집 데이터를 근거로 사용했는데, 3월 분석 기간과 동일한 이력이 있었다면 H3을 훨씬 강하게 입증할 수 있었을 겁니다."

---

## PART 7 — ROLE & MOTIVATION (직무 적합성)

---

### Q13. 이 팀에서 어떤 역할을 하고 싶으신가요?

**Script:**
> "과제 설명에서 navigation 팀의 핵심이 '데이터로 길을 더 똑똑하게 만드는 사람'이라는 표현이 인상적이었습니다.
>
> 저는 이번 과제에서 했던 것처럼 — 사용자 불만(VOC)을 데이터 문제로 변환하고, 가설을 세워 검증하고, AI 개선안까지 도출하는 — end-to-end 분석 역할을 맡고 싶습니다.
>
> 구체적으로는 경로 추천 결과 vs 실제 이동 비교 분석, '왜 이 길을 추천했는데 사람들이 안 따르지?'라는 질문에 데이터로 답하는 분석, 그리고 ETA/경로 품질 모니터링 지표를 설계하는 작업에 기여하고 싶습니다."

---

### Q14. GIS 및 공간 분석 경험이 있으신가요?

**Script:**
> "이번 과제에서 직접 사용했습니다.
>
> geopandas로 국토부 SHP 파일을 읽어 PostgreSQL에 적재하고, Folium으로 서울 도로망 위에 ETA 오차율을 히트맵으로 시각화했습니다.
>
> 특히 서울시 링크 필터링에서 LINK_ID의 앞 세 자리가 100~124인 경우만 서울시 관리 링크라는 점을 파악해 필터링 로직을 작성했습니다.
>
> 좌표계 변환도 다뤘습니다. 서울시 교통 데이터가 GRS80 TM(횡단 메르카토르) 좌표계를 사용하는데, Folium은 WGS84 위경도를 씁니다. pyproj로 변환하거나 변환 공식을 직접 적용해 지도에 정확하게 올렸습니다."

---

## PART 8 — QUICK REFERENCE NUMBERS

면접 중 머릿속에 바로 떠올릴 수 있어야 하는 숫자들:

| 항목 | 수치 |
|------|------|
| TOPIS 속도 데이터 규모 | 5,080 links × 31 days × 24 hours ≈ **3.77M rows** |
| 전국표준노드링크 (서울) | **63,288 links** |
| 분석 대상 피크 링크 | **3,611 links** (weekday 7-9am) |
| VOC1 최대 ETA 오차 | 올림픽대로 **+352%** |
| 피크 속도 급락 | 6시 71.9 → 9시 32.6 km/h = **45.5% 급락** |
| 올림픽대로 CV | **0.66** (날짜별 변동계수) |
| 전체 피크 링크 CV | **0.52** |
| 30% 초과 오차 비율 | **12.6%** of peak link-hours |
| 돌발 이벤트 (H3) | 올림픽대로 차량고장 **07:31~08:26, 55분** 지속 |
| VOC2 Route A 표준편차 | **±24.2 km/h** (8시) |
| VOC2 Route A 임계 속도 | **32.5 km/h** (이 이하면 우회로 역전) |
| 우회가 정당화된 날 | 31일 중 **10일 (32%)** |
| 우회 설명 불가 날 | 31일 중 **21일 (68%)** → H2 (갱신 lag) 원인 |
| 링크 ID 매핑률 | 5,080 중 **1,505개 (30%)** |

---

## PART 9 — POSSIBLE CODE EXERCISE

면접에서 코딩 문제가 나올 경우 대비

### 예상 문제 유형

**1. ETA 오차율 계산 함수**
```python
def calc_eta_error(distance_m, predicted_speed_kmh, actual_speed_kmh):
    """
    distance_m: 링크 거리 (m)
    predicted_speed_kmh: 예측 속도 (km/h) — 링크 전체 평균
    actual_speed_kmh: 실제 속도 (km/h) — 피크 시간대 측정
    returns: ETA 오차율 (0.30 = 30% 초과)
    """
    pred_time = distance_m / (predicted_speed_kmh * 1000 / 60)  # 분
    actual_time = distance_m / (actual_speed_kmh * 1000 / 60)   # 분
    return (actual_time - pred_time) / pred_time
```

**2. 변동계수(CV) 계산**
```python
import pandas as pd

def calc_cv_by_link(df):
    """
    df: columns = [link_id, date, hour, speed]
    returns: DataFrame with [link_id, avg_speed, std_speed, cv]
    """
    return (
        df[df['hour'].between(7, 9)]
        .groupby('link_id')['speed']
        .agg(avg_speed='mean', std_speed='std')
        .assign(cv=lambda x: x['std_speed'] / x['avg_speed'])
        .sort_values('cv', ascending=False)
    )
```

**3. Cost function으로 경로 선택**
```python
def choose_route(routes, alpha=1.0, beta=0.1):
    """
    routes: list of dict {name, travel_time_min, distance_km}
    alpha: time weight, beta: distance weight
    returns: name of chosen route (lowest cost)
    """
    costs = {
        r['name']: alpha * r['travel_time_min'] + beta * r['distance_km']
        for r in routes
    }
    return min(costs, key=costs.get)

# 사용 예시
routes = [
    {'name': 'Route A (Olympic Expressway)', 'travel_time_min': 23, 'distance_km': 18.5},
    {'name': 'Route B (Dongil-ro)',           'travel_time_min': 34, 'distance_km': 18.3},
]
print(choose_route(routes))  # Route A 선택 (정상)
print(choose_route(routes, alpha=1.0, beta=55.0))  # beta 극단 시 Route B로 역전
```

**4. Dijkstra 기본 구현**
```python
import heapq

def dijkstra(graph, start, end):
    """
    graph: {node: [(cost, neighbor), ...]}
    returns: (total_cost, path)
    """
    heap = [(0, start, [start])]
    visited = set()

    while heap:
        cost, node, path = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == end:
            return cost, path
        for edge_cost, neighbor in graph.get(node, []):
            if neighbor not in visited:
                heapq.heappush(heap, (cost + edge_cost, neighbor, path + [neighbor]))

    return float('inf'), []
```

---

## PART 10 — TERMINOLOGY CHEAT SHEET

| 용어 | 설명 |
|------|------|
| **VOC** | Voice of Customer — 고객 불만/의견 |
| **ETA** | Estimated Time of Arrival — 예상 도착 시간 |
| **Link** | 도로 네트워크의 최소 단위 구간 (두 노드 사이) |
| **Node** | 교차점, 분기점 등 도로 연결점 |
| **CV (변동계수)** | 표준편차 / 평균 — 값이 클수록 예측 불안정 |
| **TOPIS** | 서울시 교통 정보 서비스 |
| **AccInfo** | 서울 열린데이터광장 실시간 돌발 정보 API |
| **TrafficInfo** | 서울 열린데이터광장 실시간 도로 소통 정보 API |
| **GRS80 TM** | 한국 공간 데이터 표준 좌표계 (횡단 메르카토르) |
| **WGS84** | 국제 표준 GPS 위경도 좌표계 |
| **shp2pgsql** | SHP 파일 → PostgreSQL 적재 도구 |
| **exp_clr_date** | AccInfo의 예상 해제 일자 필드 — 이 값이 지나면 이벤트 해소 |
| **Cost function** | 경로 탐색에서 비용을 계산하는 함수 (α×시간 + β×거리) |
| **Heuristic** | A* 알고리즘에서 목적지까지 남은 거리 추정값 |
| **Admissible** | heuristic이 실제 비용을 과대추정하지 않는 조건 |
| **GIS** | Geographic Information System — 공간 데이터 분석 시스템 |
| **LBS** | Location Based Service — 위치 기반 서비스 |

---

*작성일: 2026-04-07*
*기반 프로젝트: navigation_analysis (현대오토에버 2026 상반기 과제 테스트)*
