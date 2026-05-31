from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    database_path: Path
    static_dir: Path
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
    brave_search_api_key: str = ""
    web_discovery_max_queries: int = 6
    web_discovery_max_results: int = 10
    web_discovery_max_content_chars: int = 250_000
    web_discovery_parallel_workers: int = 6
    analysis_job_workers: int = 4
    analysis_job_ttl_seconds: int = 900
    public_mode: bool = False

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> "Settings":
        root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        platform_port = os.getenv("PORT", "").strip()
        return cls(
            root_dir=root,
            database_path=Path(os.getenv("MINH_CHUNG_DATABASE", data_dir / "minh_chung.db")),
            static_dir=root,
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
            brave_search_api_key=os.getenv("BRAVE_SEARCH_API_KEY", "").strip(),
            web_discovery_max_queries=max(1, min(10, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_QUERIES", "6")))),
            web_discovery_max_results=max(1, min(20, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_RESULTS", "10")))),
            web_discovery_max_content_chars=max(
                10_000,
                int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_MAX_CONTENT_CHARS", "250000")),
            ),
            web_discovery_parallel_workers=max(
                1,
                min(10, int(os.getenv("MINH_CHUNG_WEB_DISCOVERY_PARALLEL_WORKERS", "6"))),
            ),
            analysis_job_workers=max(1, min(16, int(os.getenv("MINH_CHUNG_ANALYSIS_JOB_WORKERS", "4")))),
            analysis_job_ttl_seconds=max(60, int(os.getenv("MINH_CHUNG_ANALYSIS_JOB_TTL_SECONDS", "900"))),
            public_mode=os.getenv("MINH_CHUNG_PUBLIC_MODE", "0") == "1",
        )
