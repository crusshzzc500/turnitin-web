from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    database_path: Path
    static_dir: Path
    database_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8765
    crawler_user_agent: str = "MinhChungResearchBot/0.1 (+contact: admin@example.invalid)"
    crawler_delay_seconds: float = 1.5
    crawler_timeout_seconds: float = 12.0
    crawler_max_bytes: int = 2_000_000
    crawler_sitemap_max_bytes: int = 5_000_000
    crawler_allow_private_hosts: bool = False
    crawler_same_domain_only: bool = True
    crawler_max_attempts: int = 3
    crawler_retry_base_seconds: float = 30.0
    document_max_bytes: int = 250_000_000
    search_backend: str = "sqlite"
    opensearch_url: str = "http://127.0.0.1:9200"
    opensearch_index: str = "minh-chung-chunks"
    opensearch_timeout_seconds: float = 8.0
    tavily_api_key: str = ""
    exa_api_key: str = ""
    websearchapi_api_key: str = ""
    linkup_api_key: str = ""
    serper_api_key: str = ""
    brave_search_api_key: str = ""
    web_discovery_max_queries: int = 10
    web_discovery_max_results: int = 10
    web_discovery_max_content_chars: int = 250_000
    web_discovery_parallel_workers: int = 10
    web_discovery_mode: str = "fast"
    web_discovery_time_budget_seconds: float = 150.0
    web_discovery_request_timeout_seconds: float = 45.0
    web_discovery_fallback_min_sources: int = 8
    web_discovery_exa_max_queries: int = 3
    web_discovery_exa_mode: str = "instant"
    web_discovery_websearchapi_max_queries: int = 1
    web_discovery_linkup_max_queries: int = 1
    web_discovery_linkup_depth: str = "fast"
    web_discovery_serper_max_queries: int = 1
    analysis_job_workers: int = 4
    analysis_job_ttl_seconds: int = 900
    public_mode: bool = False
    auth_mode: str = "demo"
    organization_name: str = "Minh Chung Workspace"

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> "Settings":
        root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        platform_port = os.getenv("PORT", "").strip()
        database_url = os.getenv("DATABASE_URL", "").strip()
        return cls(
            root_dir=root,
            database_path=Path(os.getenv("MINH_CHUNG_DATABASE", data_dir / "minh_chung.db")),
            static_dir=root,
            database_url=database_url,
            host=os.getenv("MINH_CHUNG_HOST", "0.0.0.0" if platform_port else "127.0.0.1"),
            port=int(os.getenv("MINH_CHUNG_PORT", platform_port or "8765")),
            crawler_user_agent=os.getenv(
                "MINH_CHUNG_CRAWLER_USER_AGENT",
                "MinhChungResearchBot/0.1 (+contact: admin@example.invalid)",
            ),
            crawler_delay_seconds=float(os.getenv("MINH_CHUNG_CRAWLER_DELAY_SECONDS", "1.5")),
            crawler_timeout_seconds=float(os.getenv("MINH_CHUNG_CRAWLER_TIMEOUT_SECONDS", "12")),
            crawler_max_bytes=int(os.getenv("MINH_CHUNG_CRAWLER_MAX_BYTES", "2000000")),
            crawler_sitemap_max_bytes=int(os.getenv("MINH_CHUNG_CRAWLER_SITEMAP_MAX_BYTES", "5000000")),
            crawler_allow_private_hosts=os.getenv("MINH_CHUNG_ALLOW_PRIVATE_HOSTS", "0") == "1",
            crawler_same_domain_only=os.getenv("MINH_CHUNG_CRAWLER_SAME_DOMAIN_ONLY", "1") != "0",
            crawler_max_attempts=max(1, int(os.getenv("MINH_CHUNG_CRAWLER_MAX_ATTEMPTS", "3"))),
            crawler_retry_base_seconds=max(
                0,
                float(os.getenv("MINH_CHUNG_CRAWLER_RETRY_BASE_SECONDS", "30")),
            ),
            document_max_bytes=int(os.getenv("MINH_CHUNG_DOCUMENT_MAX_BYTES", "250000000")),
            search_backend=os.getenv("MINH_CHUNG_SEARCH_BACKEND", "sqlite").lower(),
            opensearch_url=os.getenv("MINH_CHUNG_OPENSEARCH_URL", "http://127.0.0.1:9200"),
            opensearch_index=os.getenv("MINH_CHUNG_OPENSEARCH_INDEX", "minh-chung-chunks"),
            opensearch_timeout_seconds=float(os.getenv("MINH_CHUNG_OPENSEARCH_TIMEOUT_SECONDS", "8")),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            exa_api_key=os.getenv("EXA_API_KEY", "").strip(),
            websearchapi_api_key=os.getenv("WEBSEARCHAPI_API_KEY", "").strip(),
            linkup_api_key=os.getenv("LINKUP_API_KEY", "").strip(),
            serper_api_key=os.getenv("SERPER_API_KEY", "").strip(),
            brave_search_api_key=os.getenv("BRAVE_SEARCH_API_KEY", "").strip(),
            web_discovery_max_queries=max(1, min(10, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_QUERIES", "10")))),
            web_discovery_max_results=max(1, min(20, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_RESULTS", "10")))),
            web_discovery_max_content_chars=max(
                10_000,
                int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_CONTENT_CHARS", "250000")),
            ),
            web_discovery_parallel_workers=max(
                1,
                min(10, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_PARALLEL_WORKERS", "10"))),
            ),
            web_discovery_mode=(
                os.getenv("MINH_CHUNG_WEB_DISCOVERY_MODE", "fast")
                if os.getenv("MINH_CHUNG_WEB_DISCOVERY_MODE", "fast") in {"basic", "advanced", "fast", "ultra-fast"}
                else "fast"
            ),
            web_discovery_time_budget_seconds=max(
                1.0,
                min(180.0, float(os.getenv("MINH_CHUNG_WEB_DISCOVERY_TIME_BUDGET_SECONDS", "150"))),
            ),
            web_discovery_request_timeout_seconds=max(
                1.0,
                min(60.0, float(os.getenv("MINH_CHUNG_WEB_DISCOVERY_REQUEST_TIMEOUT_SECONDS", "45"))),
            ),
            web_discovery_fallback_min_sources=max(
                1,
                min(20, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_FALLBACK_MIN_SOURCES", "8"))),
            ),
            web_discovery_exa_max_queries=max(
                1,
                min(3, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_EXA_MAX_QUERIES", "3"))),
            ),
            web_discovery_exa_mode=(
                os.getenv("MINH_CHUNG_WEB_DISCOVERY_EXA_MODE", "instant")
                if os.getenv("MINH_CHUNG_WEB_DISCOVERY_EXA_MODE", "instant") in {"instant", "fast", "auto"}
                else "instant"
            ),
            web_discovery_websearchapi_max_queries=min(
                1,
                max(1, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_WEBSEARCHAPI_MAX_QUERIES", "1"))),
            ),
            web_discovery_linkup_max_queries=min(
                1,
                max(1, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_LINKUP_MAX_QUERIES", "1"))),
            ),
            web_discovery_linkup_depth=(
                os.getenv("MINH_CHUNG_WEB_DISCOVERY_LINKUP_DEPTH", "fast")
                if os.getenv("MINH_CHUNG_WEB_DISCOVERY_LINKUP_DEPTH", "fast") in {"fast", "standard"}
                else "fast"
            ),
            web_discovery_serper_max_queries=min(
                1,
                max(1, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_SERPER_MAX_QUERIES", "1"))),
            ),
            analysis_job_workers=max(1, min(16, int(os.getenv("MINH_CHUNG_ANALYSIS_JOB_WORKERS", "4")))),
            analysis_job_ttl_seconds=max(60, int(os.getenv("MINH_CHUNG_ANALYSIS_JOB_TTL_SECONDS", "900"))),
            public_mode=False
            if database_url
            else os.getenv("MINH_CHUNG_PUBLIC_MODE", "1" if platform_port else "0") == "1",
            auth_mode=(
                "password"
                if database_url
                else (
                    os.getenv("MINH_CHUNG_AUTH_MODE", "demo").lower()
                    if os.getenv("MINH_CHUNG_AUTH_MODE", "demo").lower() in {"demo", "password"}
                    else "demo"
                )
            ),
            organization_name=os.getenv("MINH_CHUNG_ORGANIZATION_NAME", "Minh Chung Workspace").strip()
            or "Minh Chung Workspace",
        )
