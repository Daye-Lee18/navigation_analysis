from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml
from dotenv import load_dotenv
import xmltodict


# -----------------------------
# Config
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
YAML_PATH = BASE_DIR / "services.yaml"

# 실제 포털 base url로 바꿔주세요.
BASE_URL = "https://api.example.com"


@dataclass
class ServiceConfig:
    name: str
    env_key: str
    path: str
    method: str = "GET"
    response_format: str = "xml"
    description: str = ""


class TrafficApiClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        env_path: Path = ENV_PATH,
        yaml_path: Path = YAML_PATH,
        timeout: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        load_dotenv(env_path)
        self.service_map = self._load_service_configs(yaml_path)

    def _load_service_configs(self, yaml_path: Path) -> Dict[str, ServiceConfig]:
        if not yaml_path.exists():
            raise FileNotFoundError(f"services.yaml not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        services = raw.get("services", {})
        result: Dict[str, ServiceConfig] = {}

        for name, cfg in services.items():
            result[name] = ServiceConfig(
                name=name,
                env_key=cfg["env_key"],
                path=cfg["path"],
                method=cfg.get("method", "GET"),
                response_format=cfg.get("response_format", "xml"),
                description=cfg.get("description", ""),
            )
        return result

    def list_services(self) -> None:
        for name, cfg in self.service_map.items():
            print(f"- {name}: {cfg.description}")

    def _get_api_key(self, env_key: str) -> str:
        value = os.getenv(env_key)
        if not value:
            raise ValueError(f"Missing API key in .env: {env_key}")
        return value

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def call(
        self,
        service_name: str,
        params: Optional[Dict[str, Any]] = None,
        api_key_param_name: str = "serviceKey",
    ) -> Any:
        if service_name not in self.service_map:
            raise KeyError(f"Unknown service: {service_name}")

        cfg = self.service_map[service_name]
        api_key = self._get_api_key(cfg.env_key)

        request_params = dict(params or {})
        request_params[api_key_param_name] = api_key

        url = self._build_url(cfg.path)

        if cfg.method.upper() != "GET":
            raise NotImplementedError("Only GET is implemented for now.")

        resp = requests.get(url, params=request_params, timeout=self.timeout)
        resp.raise_for_status()

        if cfg.response_format.lower() == "json":
            return resp.json()

        if cfg.response_format.lower() == "xml":
            return xmltodict.parse(resp.text)

        return resp.text

    def save_response(
        self,
        service_name: str,
        output_path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        data = self.call(service_name, params=params)
        out = Path(output_path)

        if out.suffix.lower() == ".json":
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            with open(out, "w", encoding="utf-8") as f:
                f.write(str(data))

        print(f"Saved response to {out}")


def main() -> None:
    client = TrafficApiClient()

    print("[Available Services]")
    client.list_services()

    # 예시 1: 실시간 돌발 정보 호출
    # 아래 파라미터 이름은 실제 API 문서에 맞게 바꾸세요.
    try:
        data = client.call(
            "realtime_incident",
            params={
                "pageNo": 1,
                "numOfRows": 10,
            },
        )
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    except Exception as e:
        print(f"[ERROR] realtime_incident call failed: {e}")

    # 예시 2: 결과 저장
    # client.save_response(
    #     "realtime_road_traffic",
    #     "realtime_road_traffic.json",
    #     params={"pageNo": 1, "numOfRows": 100},
    # )


if __name__ == "__main__":
    main()