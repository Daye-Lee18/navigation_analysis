"""
VOC2: 이상 경로 발생 분석
===========================
불만: 평소 10km 경로로 주행 → 내비게이션이 30km 우회 경로 제공

시나리오 (실제 데이터 기반):
  Route A (직접): 올림픽대로  18.5km  — 도시고속도로, 빠른 직접 경로
  Route B (우회): 동일로+천호대로 18.3km — 주간선도로, 더 느린 우회 경로

분석 구조:
  H1. traffic 과대 추정  : 실제보다 Route A 속도를 낮게 추정해 우회 선택
  H2. road restriction 오류: 해제된 도로 통제 정보가 남아 Route A 회피
  H3. cost function bias  : 거리 vs 시간 가중치 설정 오류
  H4. rerouting 로직 문제 : 재탐색 트리거 조건 오류로 불필요한 재탐색

Output (output/):
  - voc2_h1_cost_function.png     : Route A/B 시간 비교 + 우회 선택 분기점
  - voc2_h1_daily_speed.png       : Route A 날짜별 속도 분산 (traffic 과대추정 검증)
  - voc2_h3_cost_sensitivity.png  : 거리 vs 시간 가중치 민감도 분석
  - voc2_h4_rerouting.png         : 재탐색 트리거 분석
  - voc2_map.html                 : Folium 두 경로 비교 지도
"""

import json
import warnings
from pathlib import Path

import folium
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from shapely import wkt
from shapely.geometry import MultiLineString, LineString

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.family"] = "AppleGothic"
matplotlib.rcParams["axes.unicode_minus"] = False

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent
PROCESSED_DIR = BASE_DIR / "processed"
OUTPUT_DIR    = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── VOC2 시나리오 ─────────────────────────────────────────────────────────────
SCENARIO = {
    "route_a_name":  "올림픽대로 (직접 경로)",
    "route_b_name":  "동일로·천호대로 (우회 경로)",
    "dist_a_km":     18.5,
    "dist_b_km":     18.3,
    "peak_hours":    [7, 8, 9],
    "weekdays":      ["월", "화", "수", "목", "금"],
}

ACC_INFO_URL = "http://openapi.seoul.go.kr:8088/6c747047666461793854b4c417a4c/xml/AccInfo/1/5/"


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 로드 및 경로 구성
# ─────────────────────────────────────────────────────────────────────────────
def load_routes(main_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    VOC2 시나리오용 두 경로 링크 추출

    Route A: 올림픽대로 링크 15개 (~18.5km) — 직접 고속 경로
    Route B: 동일로 + 천호대로 링크 40개 (~18.3km) — 우회 저속 경로
    """
    a_ids = main_df[main_df["도로명"] == "올림픽대로"]["링크아이디"].unique()[:15]
    b_ids = main_df[main_df["도로명"].isin(["동일로", "천호대로"])]["링크아이디"].unique()[:40]

    route_a = main_df[main_df["링크아이디"].isin(a_ids)].copy()
    route_b = main_df[main_df["링크아이디"].isin(b_ids)].copy()

    print(f"[Route A] {SCENARIO['route_a_name']}: {len(a_ids)}개 링크, {SCENARIO['dist_a_km']}km")
    print(f"[Route B] {SCENARIO['route_b_name']}: {len(b_ids)}개 링크, {SCENARIO['dist_b_km']}km")
    return route_a, route_b


def calc_route_time(route_df: pd.DataFrame, dist_km: float) -> pd.Series:
    """시간대별 평균 통행시간(분) 계산"""
    spd_by_hour = route_df.groupby("시간")["속도_kmh"].mean()
    return dist_km / spd_by_hour * 60   # 분


# ─────────────────────────────────────────────────────────────────────────────
# H1. Traffic 과대 추정
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h1_traffic_overestimate(route_a: pd.DataFrame, route_b: pd.DataFrame):
    """
    가설: 내비게이션이 Route A(직접)의 속도를 실제보다 낮게 추정
          → 예측 시간이 Route B보다 커져 우회 경로 선택

    분석 1: 시간대별 통행시간 비교 + 분기점(threshold) 계산
    분석 2: Route A 날짜별 속도 분산 → 어떤 날이 임계 이하인지
    """
    time_a = calc_route_time(route_a, SCENARIO["dist_a_km"])
    time_b = calc_route_time(route_b, SCENARIO["dist_b_km"])

    # ── (a) 시간대별 통행시간 비교 ──
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    hours = sorted(set(time_a.index) & set(time_b.index))
    x = range(len(hours))
    axes[0].bar([i - 0.2 for i in x], [time_a.get(h, np.nan) for h in hours],
                width=0.4, label=SCENARIO["route_a_name"], color="steelblue", alpha=0.85)
    axes[0].bar([i + 0.2 for i in x], [time_b.get(h, np.nan) for h in hours],
                width=0.4, label=SCENARIO["route_b_name"], color="tomato", alpha=0.85)
    axes[0].set_xticks(list(x))
    axes[0].set_xticklabels([f"{h}시" for h in hours], fontsize=8)
    axes[0].set_ylabel("예상 통행시간 (분)")
    axes[0].set_title("H1-a. 시간대별 예상 통행시간 비교\n(실제 속도 기준)", fontsize=11)
    axes[0].legend()

    # 분기점 분석: Route A 속도가 얼마나 낮아져야 Route B 선택?
    t_b_8 = time_b.get(8, 34)
    spd_a_8 = route_a[route_a["시간"] == 8]["속도_kmh"].mean()
    threshold_spd = SCENARIO["dist_a_km"] / t_b_8 * 60   # 분기점 속도
    factors = np.linspace(0.3, 1.0, 50)
    t_a_est = [SCENARIO["dist_a_km"] / (spd_a_8 * f) * 60 for f in factors]

    axes[1].plot(factors * 100, t_a_est, color="steelblue", linewidth=2, label=f"{SCENARIO['route_a_name']}")
    axes[1].axhline(t_b_8, color="tomato", linewidth=2, linestyle="--",
                    label=f"{SCENARIO['route_b_name']} ({t_b_8:.0f}분)")
    cross_pct = threshold_spd / spd_a_8 * 100
    axes[1].axvline(cross_pct, color="red", linewidth=1, linestyle=":")
    axes[1].fill_between(
        [f * 100 for f in factors if f * spd_a_8 <= threshold_spd],
        [t for f, t in zip(factors, t_a_est) if f * spd_a_8 <= threshold_spd],
        t_b_8, alpha=0.15, color="red", label=f"우회 선택 구간 (속도 < {threshold_spd:.1f}km/h)"
    )
    axes[1].set_xlabel("Route A 속도 추정치 (실제 대비 %)")
    axes[1].set_ylabel("예상 통행시간 (분)")
    axes[1].set_title(
        f"H1-b. Cost Function 분기점 분석\n"
        f"Route A 속도가 실제의 {cross_pct:.0f}% 이하여야 우회 선택", fontsize=11
    )
    axes[1].legend(fontsize=8)

    fig.suptitle("H1. Traffic 과대 추정 분석", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "voc2_h1_cost_function.png", dpi=150)
    plt.close()

    # ── (b) Route A 날짜별 속도 분산 ──
    daily_a = route_a[route_a["시간"] == 8].groupby("일자")["속도_kmh"].mean().sort_index()
    days_below = (daily_a < threshold_spd).sum()

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(daily_a.index, daily_a.values, marker="o", markersize=4, color="steelblue", label="실제 속도")
    ax.axhline(threshold_spd, color="red", linewidth=1.5, linestyle="--",
               label=f"우회 선택 임계 속도 ({threshold_spd:.1f} km/h)")
    ax.fill_between(daily_a.index,
                    [min(v, threshold_spd) for v in daily_a.values],
                    threshold_spd,
                    where=[v < threshold_spd for v in daily_a.values],
                    alpha=0.25, color="red", label=f"우회 선택 날 ({days_below}일)")
    ax.set_xlabel("날짜")
    ax.set_ylabel("8시 평균 속도 (km/h)")
    ax.set_title(
        f"H1-b. Route A(올림픽대로) 날짜별 8시 속도 (3월)\n"
        f"31일 중 {days_below}일({days_below/len(daily_a)*100:.0f}%)은 임계 이하 → 우회가 실제로 빠를 수 있음",
        fontsize=11
    )
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "voc2_h1_daily_speed.png", dpi=150)
    plt.close()

    print(f"[H1] Route A 8시 속도: 평균 {daily_a.mean():.1f}, std={daily_a.std():.1f}, min={daily_a.min():.1f}")
    print(f"[H1] 임계 속도 {threshold_spd:.1f}km/h 이하인 날: {days_below}일/{len(daily_a)}일")
    print("[H1] 저장: voc2_h1_cost_function.png, voc2_h1_daily_speed.png")

    return threshold_spd, daily_a


# ─────────────────────────────────────────────────────────────────────────────
# H2. Road Restriction 오류
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h2_road_restriction():
    """
    가설: 해제된 도로 통제 정보가 내비에 남아있어 Route A를 회피

    분석: AccInfo API로 현재 도로 통제 이벤트 확인
    시나리오: 올림픽대로 구간 통제 이벤트가 해소됐음에도 내비가 여전히 우회 경로 제공
    """
    print("[H2] AccInfo API 호출 중...")
    events = []
    try:
        resp = requests.get(ACC_INFO_URL, timeout=10)
        root = ET.fromstring(resp.text)
        for row in root.findall("row"):
            events.append({
                "acc_id":    row.findtext("acc_id"),
                "occr_date": row.findtext("occr_date"),
                "occr_time": row.findtext("occr_time"),
                "exp_clr_date": row.findtext("exp_clr_date"),
                "exp_clr_time": row.findtext("exp_clr_time"),
                "acc_type":  row.findtext("acc_type"),
                "link_id":   row.findtext("link_id"),
                "acc_info":  row.findtext("acc_info"),
                "acc_road_code": row.findtext("acc_road_code"),
            })
        print(f"[H2] 돌발 이벤트 {len(events)}건 확인")
    except Exception as e:
        print(f"[H2] AccInfo API 실패: {e}")

    # 분석 포인트 요약 (슬라이드용)
    analysis = {
        "api_events": events,
        "scenario": {
            "문제": "올림픽대로 구간 통제 이벤트 (exp_clr_date 도래) → 내비 데이터 미갱신",
            "확인_방법": [
                "AccInfo link_id가 올림픽대로 링크와 일치하는지 확인",
                "exp_clr_date/time이 현재 시각보다 이전인 이벤트 존재 여부",
                "해소된 이벤트가 내비 DB에 반영되는 갱신 주기 확인"
            ],
            "결론": "갱신 주기 지연(lag)이 있으면 실제로는 통행 가능한 도로를 계속 회피하게 됨"
        }
    }

    with open(OUTPUT_DIR / "voc2_h2_road_restriction.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print("[H2] 저장: voc2_h2_road_restriction.json")
    return events


# ─────────────────────────────────────────────────────────────────────────────
# H3. Cost Function Bias
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h3_cost_function(route_a: pd.DataFrame, route_b: pd.DataFrame):
    """
    가설: 내비게이션 cost function에서 거리 vs 시간 가중치가 잘못 설정되어
          더 긴 경로(Route B)가 더 짧은 경로(Route A)보다 낮은 cost를 갖게 됨

    cost = α × 시간(분) + β × 거리(km) + γ × 기타
    → β가 과소평가되면 거리가 길어도 패널티가 작아 우회 경로가 선택됨
    """
    t_a = calc_route_time(route_a, SCENARIO["dist_a_km"])
    t_b = calc_route_time(route_b, SCENARIO["dist_b_km"])
    d_a, d_b = SCENARIO["dist_a_km"], SCENARIO["dist_b_km"]

    # α=1(시간), β 변화에 따른 cost 비교
    betas = np.linspace(0, 3, 300)   # 거리 가중치 범위
    h8 = 8  # 8시 기준

    t_a_8 = t_a.get(h8, 23)
    t_b_8 = t_b.get(h8, 34)
    cost_a = [t_a_8 + beta * d_a for beta in betas]
    cost_b = [t_b_8 + beta * d_b for beta in betas]

    # 분기점: cost_a = cost_b
    # t_a + β*d_a = t_b + β*d_b → β*(d_a - d_b) = t_b - t_a
    # d_a > d_b이므로 β*(d_a-d_b) = t_b - t_a → β = (t_b-t_a)/(d_a-d_b)
    if abs(d_a - d_b) > 0.01:
        beta_cross = (t_b_8 - t_a_8) / (d_a - d_b)
    else:
        beta_cross = None

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # (a) beta 변화에 따른 cost
    axes[0].plot(betas, cost_a, color="steelblue", linewidth=2, label=f"Route A ({SCENARIO['route_a_name']})")
    axes[0].plot(betas, cost_b, color="tomato", linewidth=2, label=f"Route B ({SCENARIO['route_b_name']})")
    if beta_cross and 0 <= beta_cross <= 3:
        axes[0].axvline(beta_cross, color="red", linestyle=":", linewidth=1.5,
                        label=f"β 분기점 = {beta_cross:.2f}")
    axes[0].fill_between(betas,
                         cost_a, cost_b,
                         where=[ca > cb for ca, cb in zip(cost_a, cost_b)],
                         alpha=0.15, color="red", label="Route B 선택 구간")
    axes[0].set_xlabel("거리 가중치 β (분/km)")
    axes[0].set_ylabel("경로 Cost (α=1 고정)")
    axes[0].set_title("H3-a. 거리 가중치 β 변화에 따른 경로 선택\n(β가 작으면 긴 경로의 패널티 감소)", fontsize=11)
    axes[0].legend(fontsize=8)

    # (b) 시간대별 cost 비교 (β=0.5 기준)
    BETA = 0.5
    hours = sorted(set(t_a.index) & set(t_b.index))
    cost_a_by_h = [t_a.get(h, 0) + BETA * d_a for h in hours]
    cost_b_by_h = [t_b.get(h, 0) + BETA * d_b for h in hours]
    x = range(len(hours))
    axes[1].bar([i - 0.2 for i in x], cost_a_by_h, width=0.4,
                color="steelblue", alpha=0.85, label=SCENARIO["route_a_name"])
    axes[1].bar([i + 0.2 for i in x], cost_b_by_h, width=0.4,
                color="tomato", alpha=0.85, label=SCENARIO["route_b_name"])
    axes[1].set_xticks(list(x))
    axes[1].set_xticklabels([f"{h}시" for h in hours], fontsize=8)
    axes[1].set_ylabel(f"Cost (β={BETA})")
    axes[1].set_title(f"H3-b. β={BETA} 기준 시간대별 Cost 비교\n(β가 낮을수록 Route B cost 상대 감소)", fontsize=11)
    axes[1].legend(fontsize=8)

    fig.suptitle("H3. Cost Function Bias — 거리 vs 시간 가중치 민감도", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "voc2_h3_cost_sensitivity.png", dpi=150)
    plt.close()

    cross_msg = f"β = {beta_cross:.2f}" if beta_cross else "분기점 없음"
    print(f"[H3] 거리 가중치 분기점: {cross_msg}  | 저장: voc2_h3_cost_sensitivity.png")
    return beta_cross


# ─────────────────────────────────────────────────────────────────────────────
# H4. Rerouting 로직 문제
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h4_rerouting(route_a: pd.DataFrame, threshold_spd: float, daily_a: pd.Series):
    """
    가설: 재탐색(rerouting) 트리거 조건이 잘못 설정되어
          속도 일시 저하 시 불필요하게 재탐색 → 더 긴 경로 안내

    분석: Route A의 시간대별 속도 변동을 5분 간격으로 시뮬레이션
          → 임계값 이하로 잠깐 떨어지는 경우 재탐색 트리거 여부
    """
    # 30일 치 시간대별 속도 분포
    by_hour = route_a.groupby("시간")["속도_kmh"].agg(["mean", "std"]).reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # (a) 시간대별 평균 ± 1σ 밴드
    axes[0].plot(by_hour["시간"], by_hour["mean"], color="steelblue", linewidth=2, label="평균 속도")
    axes[0].fill_between(
        by_hour["시간"],
        by_hour["mean"] - by_hour["std"],
        by_hour["mean"] + by_hour["std"],
        alpha=0.2, color="steelblue", label="±1σ 범위"
    )
    axes[0].axhline(threshold_spd, color="red", linewidth=1.5, linestyle="--",
                    label=f"재탐색 임계 ({threshold_spd:.1f} km/h)")
    axes[0].fill_between(
        by_hour["시간"],
        [min(m - s, threshold_spd) for m, s in zip(by_hour["mean"], by_hour["std"])],
        threshold_spd,
        where=[(m - s) < threshold_spd for m, s in zip(by_hour["mean"], by_hour["std"])],
        alpha=0.2, color="red", label="잠재적 재탐색 구간"
    )
    axes[0].set_xlabel("시간 (시)")
    axes[0].set_ylabel("속도 (km/h)")
    axes[0].set_title("H4-a. Route A 시간대별 속도 분포\n(-1σ 구간이 임계 이하 = 재탐색 오발동 위험)", fontsize=11)
    axes[0].legend(fontsize=8)

    # (b) 일별 피크 속도 히스토그램
    axes[1].hist(daily_a.values, bins=15, color="steelblue", edgecolor="white", alpha=0.85)
    axes[1].axvline(threshold_spd, color="red", linewidth=2, linestyle="--",
                    label=f"재탐색 임계 ({threshold_spd:.1f} km/h)")
    axes[1].axvline(daily_a.mean(), color="navy", linewidth=1.5, linestyle="-",
                    label=f"평균 ({daily_a.mean():.1f} km/h)")
    below = (daily_a < threshold_spd).sum()
    axes[1].set_xlabel("8시 평균 속도 (km/h)")
    axes[1].set_ylabel("날 수")
    axes[1].set_title(
        f"H4-b. 3월 날짜별 8시 속도 히스토그램\n"
        f"임계 이하: {below}일 ({below/len(daily_a)*100:.0f}%) — 이 날 재탐색이 정당화됨",
        fontsize=11
    )
    axes[1].legend(fontsize=8)

    fig.suptitle("H4. Rerouting 로직 — 재탐색 임계값 민감도 분석", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "voc2_h4_rerouting.png", dpi=150)
    plt.close()
    print("[H4] 저장: voc2_h4_rerouting.png")


# ─────────────────────────────────────────────────────────────────────────────
# Folium 지도: 두 경로 비교
# ─────────────────────────────────────────────────────────────────────────────
def visualize_folium(main_df: pd.DataFrame, link_df: pd.DataFrame,
                     route_a: pd.DataFrame, route_b: pd.DataFrame):
    """Route A(파랑)와 Route B(빨강)를 지도에 나란히 표시"""
    db_ids = set(link_df["link_id"].tolist())
    a_ids  = set(route_a["링크아이디"].unique()) & db_ids
    b_ids  = set(route_b["링크아이디"].unique()) & db_ids

    a_geo = link_df[link_df["link_id"].isin(a_ids)].dropna(subset=["geom_wkt"]).copy()
    b_geo = link_df[link_df["link_id"].isin(b_ids)].dropna(subset=["geom_wkt"]).copy()
    a_geo["geometry"] = a_geo["geom_wkt"].apply(wkt.loads)
    b_geo["geometry"] = b_geo["geom_wkt"].apply(wkt.loads)

    m = folium.Map(location=[37.5300, 127.0800], zoom_start=12, tiles="CartoDB positron")

    def draw_route(geo_df, color, label):
        for _, row in geo_df.iterrows():
            geom = row["geometry"]
            lines = geom.geoms if isinstance(geom, MultiLineString) else [geom]
            for line in lines:
                if isinstance(line, LineString):
                    coords = [(lat, lon) for lon, lat in line.coords]
                    folium.PolyLine(
                        locations=coords, color=color,
                        weight=5, opacity=0.8, tooltip=f"{label}: {row['road_name']}"
                    ).add_to(m)

    draw_route(a_geo, "steelblue", "Route A (직접)")
    draw_route(b_geo, "tomato",    "Route B (우회)")

    legend_html = """
    <div style="position:fixed; bottom:30px; left:30px; z-index:1000;
                background:white; padding:10px; border:1px solid grey; font-size:13px;">
    <b>VOC2 경로 비교</b><br>
    <span style="color:steelblue;">━━</span> Route A: 올림픽대로 (직접, 18.5km)<br>
    <span style="color:tomato;">━━</span> Route B: 동일로·천호대로 (우회, 18.3km)
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    m.save(str(OUTPUT_DIR / "voc2_map.html"))
    print(f"[Map] 저장: voc2_map.html  (A:{len(a_geo)}개, B:{len(b_geo)}개 링크)")


# ─────────────────────────────────────────────────────────────────────────────
# 요약 리포트
# ─────────────────────────────────────────────────────────────────────────────
def print_summary(route_a, route_b, threshold_spd, daily_a, beta_cross):
    t_a_8 = calc_route_time(route_a, SCENARIO["dist_a_km"]).get(8, 0)
    t_b_8 = calc_route_time(route_b, SCENARIO["dist_b_km"]).get(8, 0)
    days_below = (daily_a < threshold_spd).sum()

    print("\n" + "=" * 60)
    print("  VOC2 이상 경로 분석 요약")
    print("=" * 60)
    print(f"  Route A 8시 실제 통행시간: {t_a_8:.0f}분")
    print(f"  Route B 8시 통행시간    : {t_b_8:.0f}분")
    print(f"  우회 선택 임계 속도     : {threshold_spd:.1f} km/h")
    print(f"  임계 이하 발생 일수     : {days_below}일 / 31일 ({days_below/31*100:.0f}%)")
    print(f"  cost function β 분기점: {beta_cross:.2f}" if beta_cross else "")
    print()
    print("  ▶ 가설 결론:")
    print(f"  H1. Route A가 실제의 {threshold_spd/daily_a.mean()*100:.0f}% 이하일 때만 우회 선택")
    print(f"      → {days_below}일은 실제로 우회가 맞지만, 나머지는 잘못된 추정")
    print("  H2. 도로 통제 해소 후 내비 DB 미갱신 → 올림픽대로 회피 지속")
    print(f"  H3. cost function β < {beta_cross:.2f} 이면 거리 패널티 부족 → 우회 유리")
    print("  H4. 재탐색 임계값이 낮으면 일시적 혼잡에도 불필요한 재탐색 발생")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  VOC2: 이상 경로 발생 분석 시작")
    print(f"  시나리오: 직접 경로(18.5km) vs 우회 경로(18.3km)")
    print("=" * 60)

    main_df = pd.read_pickle(PROCESSED_DIR / "main_dataset.pkl")
    link_df = pd.read_pickle(PROCESSED_DIR / "seoul_links.pkl")
    print(f"[load] main_dataset {len(main_df):,}행")

    route_a, route_b = load_routes(main_df)

    threshold_spd, daily_a = analyze_h1_traffic_overestimate(route_a, route_b)
    analyze_h2_road_restriction()
    beta_cross = analyze_h3_cost_function(route_a, route_b)
    analyze_h4_rerouting(route_a, threshold_spd, daily_a)
    visualize_folium(main_df, link_df, route_a, route_b)

    print_summary(route_a, route_b, threshold_spd, daily_a, beta_cross)
    print(f"\n[완료] 결과물 저장 위치: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
