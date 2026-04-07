"""
데이터 전처리 모듈
-----------------
Sources:
  1. dataset/2026년 3월 서울시 차량통행속도.xlsx  → 링크별 시간별 속도 (wide → long)
  2. dataset/02월 서울시 교통량 조사자료(2026).xlsx → 지점별 시간별 교통량 + 좌표
  3. navigation_db (PostgreSQL)                   → 서울 링크 geometry, max_spd

Output (processed/):
  - speed_long.pkl      : 속도 long format
  - volume_long.pkl     : 교통량 long format
  - spot_coords.pkl     : 교통량 수집지점 좌표
  - seoul_links.pkl     : 서울 링크 정보 (from DB)
  - main_dataset.pkl    : 속도 + 링크 정보 merge 통합 데이터
"""

import pandas as pd
import psycopg2
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent
DATASET_DIR   = BASE_DIR / "dataset"
PROCESSED_DIR = BASE_DIR / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)

# ── DB 설정 ───────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":   "localhost",
    "dbname": "navigation_db",
    "user":   "dayelee",
    "password": "0178",
    "port":   5432,
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. 차량통행속도 (3월)
# ─────────────────────────────────────────────────────────────────────────────
def load_speed_data() -> pd.DataFrame:
    """
    2026년 3월 서울시 차량통행속도 Excel 로드 → long format 변환

    원본 컬럼: 링크아이디, 거리, 도로명, ~01시~24시 (24개 속도 컬럼)
    변환 후  : 링크아이디, 일자, 시간, 속도_kmh, 통행시간_분
    """
    path = DATASET_DIR / "2026년 3월 서울시 차량통행속도.xlsx"
    df   = pd.read_excel(path)

    # wide → long
    hour_cols = [c for c in df.columns if c.endswith("시")]
    id_vars   = [
        "일자", "요일", "도로명", "링크아이디",
        "시점명", "종점명", "방향",
        "거리", "차선수", "기능유형구분", "도심/외곽구분", "권역구분",
    ]

    df_long = df.melt(
        id_vars=id_vars,
        value_vars=hour_cols,
        var_name="시간대",
        value_name="속도_kmh",
    )

    # 시간대 정수 변환: "~08시" → 8
    df_long["시간"]     = df_long["시간대"].str.extract(r"(\d+)").astype(int)
    df_long["일자"]     = pd.to_datetime(df_long["일자"].astype(str), format="%Y%m%d")
    df_long["링크아이디"] = df_long["링크아이디"].astype(str)

    # 통행시간(분) = 거리(m) / (속도(km/h) × 1000/60)
    df_long = df_long.dropna(subset=["속도_kmh"])
    df_long = df_long[df_long["속도_kmh"] > 0]   # 0 속도 제거 (측정 오류)
    df_long["통행시간_분"] = df_long["거리"] / (df_long["속도_kmh"] * 1000 / 60)

    print(f"[speed]  {len(df_long):>10,}행  |  링크 {df_long['링크아이디'].nunique():,}개  |  날짜 {df_long['일자'].nunique()}일")
    return df_long


# ─────────────────────────────────────────────────────────────────────────────
# 2. 교통량 조사자료 (2월)
# ─────────────────────────────────────────────────────────────────────────────
def load_volume_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    2월 교통량 조사자료 로드

    Returns:
        vol_long  : 지점별 일자별 시간별 교통량 (long format)
        coord_df  : 수집지점 좌표 (지점번호, 위도, 경도)
    """
    path = DATASET_DIR / "02월 서울시 교통량 조사자료(2026).xlsx"

    # ── 교통량 데이터 ──
    df_vol = pd.read_excel(path, sheet_name="2026년 02월", header=0)
    df_vol.columns = (
        ["일자", "요일", "요일2", "지점명", "지점번호", "방향", "구분"]
        + [f"{h}시" for h in range(24)]
    )
    df_vol["일자"] = pd.to_datetime(df_vol["일자"].astype(str), format="%Y%m%d")
    df_vol["지점번호"] = df_vol["지점번호"].ffill()   # 병합 셀 처리

    hour_cols = [f"{h}시" for h in range(24)]
    vol_long  = df_vol.melt(
        id_vars=["일자", "요일", "요일2", "지점명", "지점번호", "방향", "구분"],
        value_vars=hour_cols,
        var_name="시간대",
        value_name="교통량",
    )
    vol_long["시간"] = vol_long["시간대"].str.extract(r"(\d+)").astype(int)
    vol_long = vol_long.dropna(subset=["교통량"])

    # ── 수집지점 좌표 ──
    coord_df = pd.read_excel(path, sheet_name="수집지점 주소 및 좌표")
    coord_df = coord_df[["지점번호", "방향", "위도", "경도", "지점명칭"]].copy()
    coord_df["지점번호"] = coord_df["지점번호"].ffill()
    coord_df = coord_df.dropna(subset=["위도", "경도"])

    print(f"[volume] {len(vol_long):>10,}행  |  지점 {coord_df['지점번호'].nunique()}개")
    return vol_long, coord_df


# ─────────────────────────────────────────────────────────────────────────────
# 3. 서울 링크 (PostgreSQL)
# ─────────────────────────────────────────────────────────────────────────────
def load_link_from_db() -> pd.DataFrame:
    """
    navigation_db → link 테이블에서 서울 링크만 추출
    (LINK_ID 앞 3자리 100~124 = 서울)

    geometry는 WGS84(4326)로 변환된 WKT로 반환
    """
    conn = psycopg2.connect(**DB_CONFIG)
    query = """
        SELECT
            link_id,
            road_name,
            max_spd,
            length,
            ST_AsText(ST_Transform(geom, 4326)) AS geom_wkt
        FROM link
        WHERE CAST(SUBSTRING(link_id FROM 1 FOR 3) AS integer) BETWEEN 100 AND 124
    """
    df = pd.read_sql(query, conn)
    conn.close()

    print(f"[link DB] {len(df):>10,}개 서울 링크")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 4. 통합 데이터셋 생성
# ─────────────────────────────────────────────────────────────────────────────
def build_main_dataset(speed_df: pd.DataFrame, link_df: pd.DataFrame) -> pd.DataFrame:
    """
    속도 데이터 + 링크 도로 정보 merge

    파생 컬럼:
      - 속도비율    : 실제속도 / max_spd  (1이면 최고속도, 낮을수록 혼잡)
      - ETA오차율   : (실제통행시간 - 최고속기준통행시간) / 최고속기준통행시간
                     양수일수록 내비 예측보다 실제가 더 오래 걸림
    """
    merged = pd.merge(
        speed_df,
        link_df[["link_id", "road_name", "max_spd"]],
        left_on="링크아이디",
        right_on="link_id",
        how="left",
    )

    # max_spd 기준 예상 통행시간
    merged["예상통행시간_분"] = merged["거리"] / (merged["max_spd"] * 1000 / 60)

    # 실제 vs 예상 오차
    merged["ETA오차_분"]  = merged["통행시간_분"] - merged["예상통행시간_분"]
    merged["ETA오차율"]   = merged["ETA오차_분"]  / merged["예상통행시간_분"]
    merged["속도비율"]    = merged["속도_kmh"]    / merged["max_spd"]

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# 5. 평균 기준 ETA 계산 (내비게이션 예측 모사)
#    → 과거 동일 요일·시간대 평균 속도를 "예측 속도"로 사용
# ─────────────────────────────────────────────────────────────────────────────
def add_navi_eta(main_df: pd.DataFrame) -> pd.DataFrame:
    """
    내비게이션 ETA 모사: 링크별 전체 평균 속도로 예측 통행시간 계산

    실제 내비게이션은 과거 전체 이력의 평균 속도를 기반으로 ETA를 추정.
    → 같은 시간대 조건부 평균이 아닌 링크 전체 평균을 사용해야
      피크 시간대 오차(+30%)가 의미있게 나타남.

    파생 컬럼:
      - 예측속도_kmh   : 링크별 전체 평균 속도 (시간대·요일 무관)
      - 예측통행시간_분 : 거리 / 예측속도 기반
      - navi_ETA오차_분: 실제 - 예측 (양수 = 실제가 더 오래 걸림)
      - navi_ETA오차율 : navi_ETA오차_분 / 예측통행시간_분
    """
    avg_speed = (
        main_df
        .groupby("링크아이디")["속도_kmh"]
        .mean()
        .reset_index()
        .rename(columns={"속도_kmh": "예측속도_kmh"})
    )

    df = pd.merge(main_df, avg_speed, on="링크아이디", how="left")
    df["예측통행시간_분"] = df["거리"] / (df["예측속도_kmh"] * 1000 / 60)
    df["navi_ETA오차_분"] = df["통행시간_분"] - df["예측통행시간_분"]
    df["navi_ETA오차율"]  = df["navi_ETA오차_분"] / df["예측통행시간_분"]

    return df


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  데이터 전처리 시작")
    print("=" * 55)

    # 1. 속도
    speed_df = load_speed_data()
    speed_df.to_pickle(PROCESSED_DIR / "speed_long.pkl")

    # 2. 교통량 + 좌표
    vol_df, coord_df = load_volume_data()
    vol_df.to_pickle(PROCESSED_DIR / "volume_long.pkl")
    coord_df.to_pickle(PROCESSED_DIR / "spot_coords.pkl")

    # 3. 링크 (DB)
    link_df = load_link_from_db()
    link_df.to_pickle(PROCESSED_DIR / "seoul_links.pkl")

    # 4. 통합 데이터
    main_df = build_main_dataset(speed_df, link_df)
    main_df = add_navi_eta(main_df)
    main_df.to_pickle(PROCESSED_DIR / "main_dataset.pkl")

    print("\n" + "=" * 55)
    print("  저장 완료")
    print(f"  위치  : {PROCESSED_DIR}")
    print(f"  행 수  : {len(main_df):,}")
    print(f"  컬럼  : {list(main_df.columns)}")
    print("=" * 55)


if __name__ == "__main__":
    main()
