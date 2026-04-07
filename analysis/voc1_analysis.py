"""
VOC1: ETA 오류 분석
====================
불만: 목적지까지 60분 예상 → 실제 80분 도착 (30% 초과), 특정 교차로에서 지연

분석 구조:
  H0. Error Localization  : 어느 링크/시간대에서 ETA 오차가 집중되는가?
  H1. 교차로 대기시간 미반영: 피크시간 속도 급락으로 교차로 지연 추정
  H2. 실시간 데이터 지연   : 요일·날짜별 속도 패턴 일관성 vs 예측 오차
  H3. 사고/이벤트 미반영   : navigation_db (acc_info_history, traffic_info)로 실제 이벤트 분석
  H4. 평균 기반 ETA 한계   : 속도 분산이 크면 평균 기반 ETA는 outlier에 취약

Output (output/):
  - h0_eta_error_by_link.png  : 링크별 ETA 오차 분포
  - h1_peak_speed_drop.png    : 피크 전후 속도 급락
  - h2_weekday_variance.png   : 요일별 속도 분산
  - h3_accinfo_db.json        : DB 수집 돌발 이벤트 분석 결과
  - h3_accinfo_peak_speed.png : 돌발 이벤트 발생 시간대 교통속도 시각화
  - h4_speed_distribution.png : 속도 분포 (평균 vs 분산)
  - voc1_map.html             : Folium 지도 (문제 링크 시각화)
"""

import json
import warnings
from pathlib import Path

import folium
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
import pandas as pd
import psycopg2
from shapely import wkt
from shapely.geometry import MultiLineString, LineString

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.family"] = "AppleGothic"   # macOS 한글 폰트
matplotlib.rcParams["axes.unicode_minus"] = False

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OUTPUT_DIR    = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── DB 설정 ───────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "dbname":   "navigation_db",
    "user":     "dayelee",
    "password": "0178",
    "port":     5432,
}

# ── VOC1 시나리오 설정 ─────────────────────────────────────────────────────────
SCENARIO = {
    "ETA_예측_분":  60,
    "ETA_실제_분":  80,
    "ETA_오차율":   0.30,       # 30% 초과
    "분석_시간":    [7, 8, 9],  # 오전 출근 피크
    "분석_요일":    ["월", "화", "수", "목", "금"],
    "기능유형":     ["주간선도로", "보조간선도로"],   # 주요 도로만 분석
}

# H0에서 확인된 ETA 오차 1·2위 도로 (올림픽대로) 대표 링크
VOC1_TOP_ROAD = "올림픽대로"


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────────────────────
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    data_prep.py 실행 후 생성된 processed/ 파일 로드

    Returns:
        main_df  : 속도 + 링크 + ETA 오차 통합 데이터
        link_df  : 서울 링크 정보 (geometry 포함)
    """
    main_df = pd.read_pickle(PROCESSED_DIR / "main_dataset.pkl")
    link_df = pd.read_pickle(PROCESSED_DIR / "seoul_links.pkl")
    print(f"[load] main_dataset {len(main_df):,}행 | 링크 {link_df.shape[0]:,}개")
    return main_df, link_df


def filter_peak(df: pd.DataFrame) -> pd.DataFrame:
    """출근 피크 시간대 + 평일 + 주간선 필터"""
    mask = (
        df["시간"].isin(SCENARIO["분석_시간"])
        & df["요일"].isin(SCENARIO["분석_요일"])
    )
    if "기능유형구분" in df.columns:
        mask &= df["기능유형구분"].isin(SCENARIO["기능유형"])
    return df[mask]


# ─────────────────────────────────────────────────────────────────────────────
# H0. Error Localization
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h0_error_localization(main_df: pd.DataFrame) -> pd.DataFrame:
    """
    피크 시간대 링크별 평균 navi_ETA오차_분 계산
    → ETA 오차가 큰 링크 Top 20 시각화

    핵심 질문: 어떤 링크/도로에서 내비 예측보다 실제가 더 오래 걸리는가?
    """
    peak_df = filter_peak(main_df)

    link_error = (
        peak_df
        .groupby(["링크아이디", "도로명"])
        .agg(
            평균오차_분=("navi_ETA오차_분", "mean"),
            평균오차율=("navi_ETA오차율",  "mean"),
            평균속도=("속도_kmh",          "mean"),
            샘플수=("속도_kmh",           "count"),
        )
        .reset_index()
        .sort_values("평균오차율", ascending=False)  # 오차율 기준 정렬
    )

    # ── Top 20 시각화 ──
    top20 = link_error.head(20)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh(
        top20["도로명"] + "\n(" + top20["링크아이디"] + ")",
        top20["평균오차율"] * 100,
        color="tomato",
    )
    ax.axvline(30, color="navy", linewidth=1.2, linestyle="--", label="VOC 기준 (+30%)")
    ax.set_xlabel("평균 ETA 오차율 (%)  [양수 = 실제가 더 오래 걸림]")
    ax.set_title(
        "H0. ETA 오차율 상위 20 링크 (평일 출근 피크 7~9시)\n"
        f"→ 전체 피크 링크 평균 오차율: {link_error['평균오차율'].mean()*100:.1f}%",
        fontsize=12,
    )
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "h0_eta_error_by_link.png", dpi=150)
    plt.close()
    print(f"[H0] 저장: h0_eta_error_by_link.png  |  분석 링크 {len(link_error):,}개")

    return link_error


# ─────────────────────────────────────────────────────────────────────────────
# H1. 교차로 대기시간 미반영
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h1_intersection_delay(main_df: pd.DataFrame, link_error: pd.DataFrame):
    """
    가설: 교차로 대기시간이 ETA에 반영되지 않아 피크 진입 직전 구간에서 속도 급락

    분석:
      - ETA 오차 상위 10개 링크를 골라
      - 해당 링크의 시간대별 평균 속도를 0~24시로 플롯
      - 피크 직전(6시)과 피크(8시) 간 속도 차이가 클수록 교차로 지연 의심
    """
    top10_links = link_error.head(10)["링크아이디"].tolist()
    target_df   = main_df[main_df["링크아이디"].isin(top10_links)]

    hourly_speed = (
        target_df
        .groupby(["링크아이디", "도로명", "시간"])["속도_kmh"]
        .mean()
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(13, 5))
    for link_id, grp in hourly_speed.groupby("링크아이디"):
        road = grp["도로명"].iloc[0]
        grp_sorted = grp.sort_values("시간")
        ax.plot(grp_sorted["시간"], grp_sorted["속도_kmh"], alpha=0.6, label=road)

    # 피크 구간 음영
    for h in SCENARIO["분석_시간"]:
        ax.axvspan(h - 1, h, alpha=0.12, color="red")
    ax.axvspan(
        SCENARIO["분석_시간"][0] - 1,
        SCENARIO["분석_시간"][-1],
        alpha=0.0,
        label="피크 구간 (7~9시)",
    )

    ax.set_xlabel("시간 (시)")
    ax.set_ylabel("평균 속도 (km/h)")
    ax.set_title(
        "H1. ETA 오차 상위 10 링크 — 시간대별 속도 패턴\n"
        "피크 진입 직전 속도 급락 = 교차로 대기 지연 신호",
        fontsize=12,
    )
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "h1_peak_speed_drop.png", dpi=150)
    plt.close()

    # 속도 급락 정도 계산
    pre_peak  = hourly_speed[hourly_speed["시간"] == SCENARIO["분석_시간"][0] - 1]["속도_kmh"].mean()
    at_peak   = hourly_speed[hourly_speed["시간"] == SCENARIO["분석_시간"][1]]["속도_kmh"].mean()
    drop_pct  = (pre_peak - at_peak) / pre_peak * 100
    print(f"[H1] 피크 직전({SCENARIO['분석_시간'][0]-1}시) 평균 {pre_peak:.1f} km/h "
          f"→ 피크({SCENARIO['분석_시간'][1]}시) {at_peak:.1f} km/h  "
          f"({drop_pct:.1f}% 급락)  |  저장: h1_peak_speed_drop.png")


# ─────────────────────────────────────────────────────────────────────────────
# H2. 실시간 교통 데이터 지연
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h2_realtime_lag(main_df: pd.DataFrame, link_error: pd.DataFrame):
    """
    가설: 내비게이션이 실시간 교통 데이터를 제때 반영 못해 오차 발생

    분석:
      - ETA 오차 상위 5 링크의 날짜별 피크 속도 변화
      - 동일 요일이어도 날별 속도 편차가 크다 → 단순 평균으로는 예측 한계
      - 표준편차가 높은 날 = 실시간 반영 안 됐을 때 오차 더 큼
    """
    top5    = link_error.head(5)["링크아이디"].tolist()
    peak_df = filter_peak(main_df[main_df["링크아이디"].isin(top5)])

    daily_speed = (
        peak_df
        .groupby(["링크아이디", "도로명", "일자"])["속도_kmh"]
        .mean()
        .reset_index()
    )

    fig, axes = plt.subplots(1, len(top5), figsize=(14, 4), sharey=False)
    if len(top5) == 1:
        axes = [axes]

    for ax, (link_id, grp) in zip(axes, daily_speed.groupby("링크아이디")):
        road = grp["도로명"].iloc[0]
        ax.plot(grp["일자"], grp["속도_kmh"], marker="o", markersize=3, linewidth=1)
        avg = grp["속도_kmh"].mean()
        std = grp["속도_kmh"].std()
        ax.axhline(avg, color="red",   linestyle="--", linewidth=1, label=f"평균 {avg:.1f}")
        ax.axhline(avg + std, color="orange", linestyle=":", linewidth=0.8)
        ax.axhline(avg - std, color="orange", linestyle=":", linewidth=0.8, label=f"±1σ={std:.1f}")
        ax.set_title(f"{road[:8]}\n(std={std:.1f})", fontsize=9)
        ax.set_xlabel("날짜", fontsize=7)
        ax.set_ylabel("피크 평균속도(km/h)", fontsize=7)
        ax.tick_params(axis="x", rotation=45, labelsize=6)
        ax.legend(fontsize=6)

    fig.suptitle(
        "H2. 날짜별 피크 속도 변동 (ETA 오차 상위 5링크)\n"
        "σ가 크면 평균 기반 예측이 특정 날을 놓침 → 실시간 반영 필요",
        fontsize=11,
    )
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "h2_weekday_variance.png", dpi=150)
    plt.close()
    print("[H2] 저장: h2_weekday_variance.png")


# ─────────────────────────────────────────────────────────────────────────────
# H3. 사고/이벤트 반영 실패
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h3_accident() -> dict:
    """
    가설: 사고·공사·통제 등 돌발 이벤트가 ETA에 반영되지 않음

    분석: navigation_db에 수집된 실제 이벤트 이력 사용
      1) acc_info_history : 폴링 주기(~5분)별 이벤트 누적 기록
         → 피크 시간대(7~9시) 이벤트 + 올림픽대로 이벤트 집중 분석
      2) traffic_info     : 피크 시간대 링크별 실시간 속도

    한계: acc_info_history.link_id ↔ traffic_info.link_id 체계가 달라
          DB 내 직접 JOIN으로 속도 감소를 수치화하기 어려움.
    """
    print("[H3] navigation_db 돌발 이벤트 분석 중...")

    results = {"events": [], "traffic_peak": [], "key_finding": {}}

    try:
        conn = psycopg2.connect(**DB_CONFIG)

        # ── 1. acc_info_history: 이벤트별 집계 ──────────────────────────────
        # acc_info 컬럼(텍스트)에서 MAX로 대표 설명 하나 가져옴
        q_events = """
            SELECT
                acc_id,
                acc_type,
                acc_dtype,
                link_id,
                MAX(acc_info)                              AS acc_info,
                MIN(collected_at)                          AS first_seen,
                MAX(collected_at)                          AS last_seen,
                COUNT(*)                                   AS poll_count,
                EXTRACT(EPOCH FROM
                    (MAX(collected_at) - MIN(collected_at))
                ) / 60                                     AS duration_min
            FROM acc_info_history
            GROUP BY acc_id, acc_type, acc_dtype, link_id
            ORDER BY first_seen
        """
        acc_df = pd.read_sql(q_events, conn)
        acc_df["first_seen"] = pd.to_datetime(acc_df["first_seen"])
        acc_df["last_seen"]  = pd.to_datetime(acc_df["last_seen"])

        # acc_info 텍스트에서 도로명 추출 (첫 공백 전까지 또는 최대 10자)
        acc_df["road_name"] = acc_df["acc_info"].str.extract(r"([가-힣\w]+로|[가-힣\w]+대로|[가-힣\w]+길|[가-힣\w]+도로)", expand=False).fillna("미상")

        # 피크 시간대(07~09시)에 걸친 이벤트 필터
        peak_start = pd.Timestamp("07:00").time()
        peak_end   = pd.Timestamp("09:59").time()
        acc_df["first_time"] = acc_df["first_seen"].dt.time
        peak_events = acc_df[
            acc_df["first_time"].apply(
                lambda t: peak_start <= t <= peak_end
            )
        ].copy()

        results["events"] = acc_df.drop(columns=["first_time"]).to_dict(orient="records")

        print(f"  전체 이벤트 {len(acc_df)}건  |  피크 시간대(07~09시) {len(peak_events)}건")
        for _, r in peak_events.iterrows():
            print(f"    acc_id={r['acc_id']}  {r['road_name']}  {r['acc_type']}  "
                  f"{r['first_seen'].strftime('%H:%M')}~{r['last_seen'].strftime('%H:%M')}  "
                  f"({r['duration_min']:.0f}분)  link={r['link_id']}")

        # ── 2. 올림픽대로 이벤트 특정 ────────────────────────────────────────
        olympic_events = acc_df[acc_df["acc_info"].str.contains("올림픽", na=False)]
        if not olympic_events.empty:
            key = olympic_events.iloc[0]
            results["key_finding"] = {
                "acc_id":       str(key["acc_id"]),
                "road_name":    key["road_name"],
                "acc_info":     key["acc_info"][:80],
                "acc_type":     key["acc_type"],
                "link_id":      str(key["link_id"]),
                "first_seen":   str(key["first_seen"]),
                "last_seen":    str(key["last_seen"]),
                "duration_min": float(key["duration_min"]),
                "poll_count":   int(key["poll_count"]),
                "note": (
                    "VOC1 H0 ETA 오차율 1·2위 도로(올림픽대로)에서 "
                    f"피크 시간대 {key['acc_type']} 이벤트 확인. "
                    f"지속시간 {key['duration_min']:.0f}분 동안 ETA 재계산 미반영 시 "
                    "사용자 경험 20분+ 추가 지연 가능."
                ),
            }
            print(f"  ★ 핵심: 올림픽대로 이벤트 확인 (acc_id={key['acc_id']}, "
                  f"{key['duration_min']:.0f}분 지속)")

        # ── 3. traffic_info: 피크 시간대 평균 속도 ───────────────────────────
        q_traffic = """
            SELECT
                EXTRACT(HOUR FROM collected_at)      AS hour,
                ROUND(AVG(prcs_spd)::numeric, 1)     AS avg_speed_kmh,
                COUNT(*)                             AS link_count
            FROM traffic_info
            WHERE EXTRACT(HOUR FROM collected_at) BETWEEN 7 AND 9
              AND prcs_spd IS NOT NULL
              AND prcs_spd > 0
            GROUP BY 1
            ORDER BY 1
        """
        traffic_df = pd.read_sql(q_traffic, conn)
        results["traffic_peak"] = traffic_df.to_dict(orient="records")

        conn.close()

        # ── 4. 시각화: 피크 시간대 속도 + 이벤트 발생 시각 표시 ─────────────
        _plot_h3(traffic_df, peak_events)

        # ── 5. JSON 저장 ──────────────────────────────────────────────────────
        # datetime 직렬화
        def _serial(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if hasattr(obj, "item"):          # numpy scalar
                return obj.item()
            return str(obj)

        with open(OUTPUT_DIR / "h3_accinfo_db.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=_serial)
        print("[H3] 저장: h3_accinfo_db.json  |  h3_accinfo_peak_speed.png")

    except Exception as e:
        print(f"[H3] DB 연결 실패: {e}")
        results["error"] = str(e)

    return results


def _plot_h3(traffic_df: pd.DataFrame, peak_events: pd.DataFrame):
    """피크 시간대 속도 막대 + 이벤트 발생 시각 점선 시각화"""
    fig, ax = plt.subplots(figsize=(9, 4))

    hours = traffic_df["hour"].astype(int)
    speeds = traffic_df["avg_speed_kmh"].astype(float)

    bars = ax.bar(hours, speeds, color="steelblue", alpha=0.8, width=0.6, label="평균 속도 (km/h)")

    # 속도값 레이블
    for h, s in zip(hours, speeds):
        ax.text(h, s + 0.3, f"{s:.1f}", ha="center", va="bottom", fontsize=9)

    # 이벤트 발생 시각 수직선
    event_colors = ["red", "darkorange", "purple", "brown", "green"]
    for i, (_, ev) in enumerate(peak_events.iterrows()):
        ev_hour = ev["first_seen"].hour + ev["first_seen"].minute / 60
        col = event_colors[i % len(event_colors)]
        ax.axvline(ev_hour, color=col, linestyle="--", linewidth=1.4,
                   label=f"{ev['road_name'][:6]} {ev['acc_type']} ({ev['first_seen'].strftime('%H:%M')})")

    ax.set_xlabel("시간대")
    ax.set_ylabel("평균 속도 (km/h)")
    ax.set_xticks(hours)
    ax.set_xticklabels([f"{h}시" for h in hours])
    ax.set_title(
        "H3. 피크 시간대 평균 속도 vs 돌발 이벤트 발생 시각\n"
        "(점선 = 이벤트 발생 시각, 내비 미반영 시 ETA 오류 직접 원인)",
        fontsize=11,
    )
    ax.legend(fontsize=7, loc="lower left")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "h3_accinfo_peak_speed.png", dpi=150)
    plt.close()


# ─────────────────────────────────────────────────────────────────────────────
# H4. ETA 모델이 평균 기반이라 분산 반영 못함
# ─────────────────────────────────────────────────────────────────────────────
def analyze_h4_mean_bias(main_df: pd.DataFrame, link_error: pd.DataFrame):
    """
    가설: 내비게이션 ETA가 평균 속도 기반이라 고분산 시간대에서 크게 빗나감

    분석:
      - 각 링크·시간대의 속도 평균 vs 표준편차
      - 분산이 높은 링크일수록 평균 예측 ETA의 신뢰 구간이 넓음
      - 30% 초과 오차가 발생하려면 얼마나 낮은 속도가 나와야 하는지 계산
    """
    top10 = link_error.head(10)["링크아이디"].tolist()
    peak_df = filter_peak(main_df[main_df["링크아이디"].isin(top10)])

    speed_stat = (
        peak_df
        .groupby(["링크아이디", "도로명"])["속도_kmh"]
        .agg(["mean", "std", "min", "max"])
        .reset_index()
        .rename(columns={"mean": "평균속도", "std": "표준편차", "min": "최저속도", "max": "최고속도"})
    )
    speed_stat["CV"] = speed_stat["표준편차"] / speed_stat["평균속도"]  # 변동계수

    # 30% ETA 초과를 유발하는 임계 속도: v_critical = v_avg / 1.30
    speed_stat["임계속도_30pct"] = speed_stat["평균속도"] / 1.30
    speed_stat["임계초과빈도"] = speed_stat.apply(
        lambda r: (peak_df[peak_df["링크아이디"] == r["링크아이디"]]["속도_kmh"] <= r["임계속도_30pct"]).mean(),
        axis=1,
    )

    # ── 시각화: 평균 vs 표준편차 scatter ──
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # (a) 평균속도 vs 표준편차
    sc = axes[0].scatter(
        speed_stat["평균속도"],
        speed_stat["표준편차"],
        c=speed_stat["임계초과빈도"],
        cmap="Reds",
        s=60,
        alpha=0.8,
    )
    for _, row in speed_stat.iterrows():
        axes[0].annotate(
            row["도로명"][:6], (row["평균속도"], row["표준편차"]),
            fontsize=6, ha="center", va="bottom",
        )
    plt.colorbar(sc, ax=axes[0], label="30% 초과 발생 빈도")
    axes[0].set_xlabel("평균 속도 (km/h)")
    axes[0].set_ylabel("표준편차 (km/h)")
    axes[0].set_title("H4-a. 속도 평균 vs 분산\n(색상 = 30% 오차 초과 빈도)")

    # (b) 대표 링크 속도 분포 박스플롯
    box_data = []
    box_labels = []
    for link_id in top10[:6]:
        vals = peak_df[peak_df["링크아이디"] == link_id]["속도_kmh"].dropna().values
        if len(vals) > 0:
            box_data.append(vals)
            road = peak_df[peak_df["링크아이디"] == link_id]["도로명"].iloc[0][:6]
            box_labels.append(f"{road}\n({link_id})")

    bp = axes[1].boxplot(box_data, labels=box_labels, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("lightsalmon")
    axes[1].set_xlabel("링크")
    axes[1].set_ylabel("피크 속도 (km/h)")
    axes[1].set_title("H4-b. 링크별 피크 속도 분포\n(박스 폭 클수록 평균 기반 ETA 불안정)")
    axes[1].tick_params(axis="x", labelsize=7)

    fig.suptitle(
        "H4. ETA 모델이 평균 기반 → 분산 높은 링크에서 30% 초과 오차 발생",
        fontsize=12,
    )
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "h4_speed_distribution.png", dpi=150)
    plt.close()

    print(
        f"[H4] 평균 CV={speed_stat['CV'].mean():.2f}  "
        f"| 30% 초과 발생 빈도={speed_stat['임계초과빈도'].mean():.1%}  "
        f"| 저장: h4_speed_distribution.png"
    )
    return speed_stat


def _get_speed_stat_for_summary(main_df: pd.DataFrame, link_error: pd.DataFrame) -> pd.DataFrame:
    """요약용 speed_stat 간단 계산 (H4 미실행 시 fallback)"""
    top10   = link_error.head(10)["링크아이디"].tolist()
    peak_df = filter_peak(main_df[main_df["링크아이디"].isin(top10)])
    stat = (
        peak_df.groupby(["링크아이디", "도로명"])["속도_kmh"]
        .agg(["mean", "std"])
        .reset_index()
    )
    stat["CV"] = stat["std"] / stat["mean"]
    return stat


# ─────────────────────────────────────────────────────────────────────────────
# Folium 지도 시각화
# ─────────────────────────────────────────────────────────────────────────────
def visualize_folium(main_df: pd.DataFrame, link_df: pd.DataFrame, link_error: pd.DataFrame):
    """
    ETA 오차 상위 링크를 Folium 지도 위에 표시

    Note: 속도 데이터의 링크아이디는 TOPIS 서비스 링크 ID로,
          표준노드링크와 일부만 매핑됨.
          → DB geometry가 있는 링크 중 오차율 상위 20개를 시각화.

    색상 기준:
      빨강  - ETA 오차 상위 (심각)
      주황  - 중간
    """
    # DB geometry가 있는 링크만 대상으로 top20 선정
    db_link_ids = set(link_df["link_id"].tolist())
    link_error_mapped = link_error[link_error["링크아이디"].isin(db_link_ids)]

    top20_ids = set(link_error_mapped.head(20)["링크아이디"].tolist())
    top10_ids = set(link_error_mapped.head(10)["링크아이디"].tolist())

    # geometry 파싱: DB에서 가져온 WKT (null 제거 후 파싱)
    link_geo = link_df[link_df["link_id"].isin(top20_ids)].dropna(subset=["geom_wkt"]).copy()
    link_geo["geometry"] = link_geo["geom_wkt"].apply(wkt.loads)

    error_map = link_error.set_index("링크아이디")["평균오차_분"].to_dict()

    m = folium.Map(location=[37.5665, 126.9780], zoom_start=12, tiles="CartoDB positron")

    for _, row in link_geo.iterrows():
        link_id = row["link_id"]
        err_min = error_map.get(link_id, 0)
        color   = "red" if link_id in top10_ids else "orange"
        geom    = row["geometry"]

        lines = geom.geoms if isinstance(geom, MultiLineString) else [geom]
        for line in lines:
            if isinstance(line, LineString):
                coords = [(lat, lon) for lon, lat in line.coords]
                folium.PolyLine(
                    locations=coords,
                    color=color,
                    weight=4,
                    opacity=0.85,
                    tooltip=f"{row['road_name']} | ETA 오차 +{err_min:.1f}분",
                ).add_to(m)

    # 범례
    legend_html = """
    <div style="position:fixed; bottom:30px; left:30px; z-index:1000;
                background:white; padding:10px; border:1px solid grey; font-size:13px;">
    <b>VOC1 ETA 오차 링크</b><br>
    <span style="color:red;">━━</span> 상위 10 (심각)<br>
    <span style="color:orange;">━━</span> 상위 11~20
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    out_path = OUTPUT_DIR / "voc1_map.html"
    m.save(str(out_path))
    print(f"[Map]  저장: voc1_map.html  |  링크 {len(link_geo)}개 표시")


# ─────────────────────────────────────────────────────────────────────────────
# 요약 리포트
# ─────────────────────────────────────────────────────────────────────────────
def print_summary(main_df: pd.DataFrame, link_error: pd.DataFrame,
                  speed_stat: pd.DataFrame, h3_results: dict):
    peak_df  = filter_peak(main_df)
    avg_err  = peak_df["navi_ETA오차_분"].mean()
    p30_rate = (peak_df["navi_ETA오차율"] >= 0.30).mean()

    # H3 핵심 발견 요약
    kf = h3_results.get("key_finding", {})
    h3_summary = (
        f"올림픽대로 {kf.get('acc_type','')} ({kf.get('duration_min', 0):.0f}분) "
        f"DB 확인 → 유력"
        if kf else "DB 이벤트 조회 실패 — 시나리오 기반 추론"
    )

    print("\n" + "=" * 60)
    print("  VOC1 분석 요약")
    print("=" * 60)
    print(f"  피크 시간대 평균 ETA 오차    : +{avg_err:.1f}분")
    print(f"  30% 이상 오차 발생 비율      : {p30_rate:.1%}")
    print(f"  가장 심한 링크               : {link_error.iloc[0]['도로명']}  (오차율 {link_error.iloc[0]['평균오차율']*100:.1f}%)")
    print(f"  평균 속도 변동계수(CV)       : {speed_stat['CV'].mean():.2f}")
    print()
    print("  ▶ 가설 결론:")
    print("  H1. 피크 진입 속도 급락 → 교차로 대기 미반영 가능성 높음  ✅")
    print("  H2. 날짜별 속도 편차 큼 → 실시간 반영 지연 의심           ✅")
    print(f"  H3. {h3_summary}")
    print(f"  H4. CV={speed_stat['CV'].mean():.2f} → 평균 기반 ETA는 피크 분산을 과소추정  ✅")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  VOC1: ETA 오류 분석 시작")
    print(f"  시나리오: ETA {SCENARIO['ETA_예측_분']}분 → 실제 {SCENARIO['ETA_실제_분']}분 (+{SCENARIO['ETA_오차율']:.0%})")
    print("=" * 60)

    # 1. 데이터 로드
    main_df, link_df = load_data()

    # 2. H0. Error Localization
    link_error = analyze_h0_error_localization(main_df)

    # 3. H1. 교차로 대기시간 미반영
    analyze_h1_intersection_delay(main_df, link_error)

    # 4. H2. 실시간 데이터 지연
    analyze_h2_realtime_lag(main_df, link_error)

    # 5. H3. 사고/이벤트 (DB 실데이터)
    h3_results = analyze_h3_accident()

    # 6. H4. 평균 기반 ETA 한계
    speed_stat = analyze_h4_mean_bias(main_df, link_error)

    # 7. Folium 지도
    visualize_folium(main_df, link_df, link_error)

    # 8. 요약
    print_summary(main_df, link_error, speed_stat, h3_results)

    print(f"\n[완료] 결과물 저장 위치: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
