import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime
import time
import traceback

API_KEY = "58775479626461793838746d657374"
DB_USER = "dayelee"
DB_PASSWORD = "'0178'"
DB_NAME = "navigation_db"
DB_HOST = "localhost"
DB_PORT = 5432
NUM_LINK_ID = 10000


def check_api_result(result_code: str, result_message: str | None = None) -> tuple[bool, str]:
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


def load_link_ids(cur, limit_count: int) -> list[str]:
    query = """
        SELECT CAST(link_id AS TEXT)
        FROM link
        WHERE link_id IS NOT NULL
          AND CAST(SUBSTRING(CAST(link_id AS TEXT) FROM 1 FOR 3) AS integer) BETWEEN 100 AND 124
        LIMIT %s
    """
    cur.execute(query, (limit_count,))
    return [row[0] for row in cur.fetchall()]


def main():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )
    cur = conn.cursor()

    try:
        link_ids = load_link_ids(cur, NUM_LINK_ID)
        print(f"수집 대상 link 수: {len(link_ids)}")

        while True:
            for link_id in link_ids:
                url = f"http://openapi.seoul.go.kr:8088/{API_KEY}/xml/TrafficInfo/1/5/{link_id}"

                try:
                    response = requests.get(url, timeout=10)
                    response.raise_for_status()

                    root = ET.fromstring(response.text)

                    result_code = root.findtext("RESULT/CODE")
                    result_message = root.findtext("RESULT/MESSAGE")
                    rows = root.findall("row")

                    is_success, status_msg = check_api_result(result_code, result_message)

                    if not is_success:
                        print(f"{link_id} 응답 비정상: {status_msg}")
                        continue

                    for row in rows:
                        api_link_id = row.findtext("link_id")
                        prcs_spd = row.findtext("prcs_spd")
                        prcs_trv_time = row.findtext("prcs_trv_time")

                        cur.execute("""
                            INSERT INTO traffic_info (
                                link_id, prcs_spd, prcs_trv_time,
                                result_code, result_message, collected_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            api_link_id,
                            float(prcs_spd) if prcs_spd else None,
                            int(prcs_trv_time) if prcs_trv_time else None,
                            result_code,
                            result_message,
                            datetime.now()
                        ))

                    conn.commit()
                    print(f"{link_id} 저장 완료")

                except Exception as e:
                    try:
                        if conn and not conn.closed:
                            conn.rollback()
                    except Exception:
                        pass

                    print(f"{link_id} 실패: {e}")
                    traceback.print_exc()

                time.sleep(0.2)

    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass

        try:
            if conn and not conn.closed:
                conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()