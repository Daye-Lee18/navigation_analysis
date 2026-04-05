# navigation_analysis
Navigation Analalysis 

project/
|- .env 
|- services.yaml
|- api_client.py
|- requirements.txt 


# folder structure 

## projects 

나중에 API를 하나더 추가하더라도 .env 만 수정, 서비스를 추가하면 services.yaml만 수정, 비지니스 로직은 python에서만 확장하면 돼서 간편하다. 

* .env: API keys 
* services.yaml: 서비스 이름, 엔드포인트, 응답 형식, 기본 파라미터 
* api_client.py: .evn, yaml, 서비스명으로 api 호출, xml/json 파싱, postgres에 데이터 적재