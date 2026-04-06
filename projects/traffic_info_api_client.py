import requests
import xml.etree.ElementTree as ET
import psycopg2
from psycopg2 import sql
from datetime import datetime
import time 

API_KEY = "58775479626461793838746d657374"
# LINK_ID = "1000000301"
DB_USER = "dayelee"
DB_PASSWORD = "'0178'"  
DB_NAME = "navigation_db"
DB_HOST = "localhost"
DB_PORT = 5432
NUM_LINK_ID = 10000


conn = psycopg2.connect(
    host="localhost",
    dbname="navigation_db",
    user=DB_USER,   
    password=DB_PASSWORD,
    port=DB_PORT
)

cur = conn.cursor()

# ------------------------- 링크가져오기 
# 실험용: 링크 20개만 가져오기
query = """
    SELECT link_id
    FROM link
    WHERE link_id IS NOT NULL
      AND CAST(SUBSTRING(link_id FROM 1 FOR 3) AS integer) BETWEEN 100 AND 124
    LIMIT %s
"""
cur.execute(query, (NUM_LINK_ID,))

link_ids = [row[0] for row in cur.fetchall()]

# URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/xml/TrafficInfo/1/5/{LINK_ID}"

def check_api_result(result_code: str, result_message: str | None = None) -> tuple[bool, str]:
    """
    API 결과코드를 해석해서
    - 정상 처리 여부
    - 사용자에게 보여줄 메시지
    를 반환한다.

    Returns:
        (is_success, message)
    """
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

    # 정상 처리
    if result_code == "INFO-000":
        return True, code_messages[result_code]

    # 정상 제외: 모두 처리 안 됨 / 실패 / 예외로 취급
    default_msg = f"처리되지 않았습니다. result_code={result_code}"
    detail_msg = code_messages.get(result_code, default_msg)

    # API에서 내려준 원본 메시지가 있으면 같이 붙임
    if result_message and result_message.strip():
        detail_msg = f"{detail_msg} (API 메시지: {result_message})"

    return False, detail_msg

def main():
    while True:
        for link_id in link_ids:
            url = f"http://openapi.seoul.go.kr:8088/{API_KEY}/xml/TrafficInfo/1/5/{link_id}"

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()

                root = ET.fromstring(response.text)

                result_code = root.findtext("RESULT/CODE")
                result_message = root.findtext("RESULT/MESSAGE")
        # <?xml version="1.0" encoding="UTF-8" standalone="yes"?><TrafficInfo><list_total_count>1</list_total_count><RESULT><CODE>INFO-000</CODE><MESSAGE>정상 처리되었습니다</MESSAGE></RESULT><row><link_id>1220003800</link_id><prcs_spd>89</prcs_spd><prcs_trv_time>121</prcs_trv_time></row></TrafficInfo>
                rows = root.findall("row")
                
                is_success, status_msg = check_api_result(result_code, result_message)

                if not is_success:
                    print(status_msg)
                    continue 
                    # 중간에 바로 멈추기 
                    # if not is_success:
                    #     print(status_msg)
                    #     cur.close()
                    #     conn.close()
                    #     raise RuntimeError(status_msg)
                else:
                    print("정상 처리:", status_msg)

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
                

            except Exception as e:
                conn.rollback()
                print(f"{link_id} 실패: {e}")

            time.sleep(0.2)  # 너무 빠른 연속 호출 방지

        cur.close()
        conn.close()

    print("여러 링크 traffic_info 적재 완료")


if __name__ == "__main__":
    main()
