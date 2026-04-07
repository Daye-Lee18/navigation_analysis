import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime
import time
from typing import Optional

API_KEY = "6c7470476664617938354b4c417a4c"

DB_USER = "dayelee"
DB_PASSWORD = "'0178'"
DB_NAME = "navigation_db"
DB_HOST = "localhost"
DB_PORT = 5432

BASE_URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/xml/AccInfo"
PAGE_SIZE = 1000          # API 문서상 최대 1000건
POLL_INTERVAL = 300       # 5분마다 반복 수집, 필요시 조정


def safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def safe_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def check_api_result(result_code: str, result_message: Optional[str] = None) -> tuple[bool, str]:
    code_messages = {
        "INFO-000": "정상 처리되었습니다.",
        "ERROR-300": "필수값이 누락되어 있습니다. 요청 인자를 확인하세요.",
        "INFO-100": "인증키가 유효하지 않습니다. 인증키를 확인하세요.",
        "ERROR-301": "파일타입(TYPE) 값이 누락되었거나 유효하지 않습니다.",
        "ERROR-310": "해당 서비스를 찾을 수 없습니다. SERVICE 값을 확인하세요.",
        "ERROR-331": "요청 시작 위치(START_INDEX) 값을 확인하세요.",
        "ERROR-332": "요청 종료 위치(END_INDEX) 값을 확인하세요.",
        "ERROR-333": "요청 위치 값의 타입이 유효하지 않습니다. 정수를 입력하세요.",
        "ERROR-334": "요청 종료 위치보다 요청 시작 위치가 큽니다.",
        "ERROR-335": "샘플데이터는 한 번에 최대 5건까지만 요청할 수 있습니다.",
        "ERROR-336": "데이터 요청은 한 번에 최대 1000건을 넘을 수 없습니다.",
        "ERROR-500": "서버 오류입니다.",
        "ERROR-600": "데이터베이스 연결 오류입니다.",
        "ERROR-601": "SQL 문장 오류입니다.",
        "INFO-200": "해당하는 데이터가 없습니다.",
    }

    if result_code == "INFO-000":
        return True, code_messages[result_code]

    default_msg = f"처리되지 않았습니다. result_code={result_code}"
    detail_msg = code_messages.get(result_code, default_msg)

    if result_message and result_message.strip():
        detail_msg = f"{detail_msg} (API 메시지: {result_message})"

    return False, detail_msg


def create_table_if_not_exists(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS acc_info_history (
            id BIGSERIAL PRIMARY KEY,
            acc_id BIGINT NOT NULL,
            occr_date VARCHAR(8),
            occr_time VARCHAR(6),
            exp_clr_date VARCHAR(8),
            exp_clr_time VARCHAR(6),
            acc_type VARCHAR(10),
            acc_dtype VARCHAR(20),
            link_id VARCHAR(20),
            grs80tm_x DOUBLE PRECISION,
            grs80tm_y DOUBLE PRECISION,
            acc_info TEXT,
            acc_road_code VARCHAR(10),
            result_code VARCHAR(20),
            result_message TEXT,
            collected_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_acc_hist_acc_id
        ON acc_info_history(acc_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_acc_hist_link_id
        ON acc_info_history(link_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_acc_hist_occr_date
        ON acc_info_history(occr_date)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_acc_hist_acc_type
        ON acc_info_history(acc_type)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_acc_hist_collected_at
        ON acc_info_history(collected_at)
    """)
def fetch_page(start_index: int, end_index: int) -> ET.Element:
    url = f"{BASE_URL}/{start_index}/{end_index}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return ET.fromstring(response.text)

def insert_rows(cur, rows, result_code: str, result_message: Optional[str], valid_link_ids: set[str]):
    now = datetime.now()

    for row in rows:
        api_link_id = safe_str(row.findtext("link_id"))

        if api_link_id is None or api_link_id not in valid_link_ids:
            continue

        acc_id = safe_int(row.findtext("acc_id"))
        if acc_id is None:
            continue

        cur.execute("""
            INSERT INTO acc_info_history (
                acc_id,
                occr_date,
                occr_time,
                exp_clr_date,
                exp_clr_time,
                acc_type,
                acc_dtype,
                link_id,
                grs80tm_x,
                grs80tm_y,
                acc_info,
                acc_road_code,
                result_code,
                result_message,
                collected_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            acc_id,
            safe_str(row.findtext("occr_date")),
            safe_str(row.findtext("occr_time")),
            safe_str(row.findtext("exp_clr_date")),
            safe_str(row.findtext("exp_clr_time")),
            safe_str(row.findtext("acc_type")),
            safe_str(row.findtext("acc_dtype")),
            api_link_id,
            safe_float(row.findtext("grs80tm_x")),
            safe_float(row.findtext("grs80tm_y")),
            safe_str(row.findtext("acc_info")),
            safe_str(row.findtext("acc_road_code")),
            result_code,
            result_message,
            now
        ))

def upsert_rows(cur, rows, result_code: str, result_message: Optional[str], valid_link_ids: set[str]):
    now = datetime.now()

    for row in rows:
        api_link_id = safe_str(row.findtext("link_id"))

        # link_id가 없거나, 우리가 허용한 서울 link 집합에 없으면 스킵
        if api_link_id is None or api_link_id not in valid_link_ids:
            continue

        acc_id = safe_int(row.findtext("acc_id"))
        if acc_id is None:
            continue

        cur.execute("""
            INSERT INTO acc_info (
                acc_id,
                occr_date,
                occr_time,
                exp_clr_date,
                exp_clr_time,
                acc_type,
                acc_dtype,
                link_id,
                grs80tm_x,
                grs80tm_y,
                acc_info,
                acc_road_code,
                result_code,
                result_message,
                collected_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (acc_id)
            DO UPDATE SET
                occr_date = EXCLUDED.occr_date,
                occr_time = EXCLUDED.occr_time,
                exp_clr_date = EXCLUDED.exp_clr_date,
                exp_clr_time = EXCLUDED.exp_clr_time,
                acc_type = EXCLUDED.acc_type,
                acc_dtype = EXCLUDED.acc_dtype,
                link_id = EXCLUDED.link_id,
                grs80tm_x = EXCLUDED.grs80tm_x,
                grs80tm_y = EXCLUDED.grs80tm_y,
                acc_info = EXCLUDED.acc_info,
                acc_road_code = EXCLUDED.acc_road_code,
                result_code = EXCLUDED.result_code,
                result_message = EXCLUDED.result_message,
                collected_at = EXCLUDED.collected_at
        """, (
            acc_id,
            safe_str(row.findtext("occr_date")),
            safe_str(row.findtext("occr_time")),
            safe_str(row.findtext("exp_clr_date")),
            safe_str(row.findtext("exp_clr_time")),
            safe_str(row.findtext("acc_type")),
            safe_str(row.findtext("acc_dtype")),
            api_link_id,
            safe_float(row.findtext("grs80tm_x")),
            safe_float(row.findtext("grs80tm_y")),
            safe_str(row.findtext("acc_info")),
            safe_str(row.findtext("acc_road_code")),
            result_code,
            result_message,
            now
        ))

def load_valid_link_ids(cur) -> set[str]:
    cur.execute("""
        SELECT CAST(link_id AS TEXT)
        FROM link
        WHERE link_id IS NOT NULL
          AND CAST(SUBSTRING(CAST(link_id AS TEXT) FROM 1 FOR 3) AS integer) BETWEEN 100 AND 124
    """)
    return {row[0] for row in cur.fetchall()}
def collect_once(conn):
    with conn.cursor() as cur:
        create_table_if_not_exists(cur)
        conn.commit()

        valid_link_ids = load_valid_link_ids(cur)
        print(f"유효 서울 link 수: {len(valid_link_ids)}")

        # 첫 페이지 조회
        root = fetch_page(1, PAGE_SIZE)

        result_code = root.findtext("RESULT/CODE")
        result_message = root.findtext("RESULT/MESSAGE")
        is_success, status_msg = check_api_result(result_code, result_message)

        if not is_success:
            raise RuntimeError(status_msg)

        total_count = safe_int(root.findtext("list_total_count")) or 0
        page_rows = root.findall("row")

        print(f"[1차 조회] total_count={total_count}, rows={len(page_rows)}")

        insert_rows(cur, page_rows, result_code, result_message, valid_link_ids)
        conn.commit()

        start = PAGE_SIZE + 1
        while start <= total_count:
            end = min(start + PAGE_SIZE - 1, total_count)

            try:
                root = fetch_page(start, end)

                result_code = root.findtext("RESULT/CODE")
                result_message = root.findtext("RESULT/MESSAGE")
                is_success, status_msg = check_api_result(result_code, result_message)

                if not is_success:
                    print(f"[페이지 {start}-{end}] 실패: {status_msg}")
                    start += PAGE_SIZE
                    continue

                page_rows = root.findall("row")
                insert_rows(cur, page_rows, result_code, result_message, valid_link_ids)
                conn.commit()

                print(f"[페이지 {start}-{end}] 저장 완료: {len(page_rows)}건")

            except Exception as e:
                conn.rollback()
                print(f"[페이지 {start}-{end}] 예외 발생: {e}")

            time.sleep(0.2)
            start += PAGE_SIZE

def main():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )

    try:
        while True:
            try:
                print(f"\n[{datetime.now()}] AccInfo 수집 시작")
                collect_once(conn)
                print(f"[{datetime.now()}] AccInfo 수집 완료")
            except Exception as e:
                conn.rollback()
                print(f"수집 실패: {e}")

            print(f"{POLL_INTERVAL}초 대기 후 재수집")
            time.sleep(POLL_INTERVAL)

    finally:
        conn.close()


if __name__ == "__main__":
    main()