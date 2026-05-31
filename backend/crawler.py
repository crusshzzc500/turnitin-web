from __future__ import annotations

import ipaddress
import gzip
import socket
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from .config import Settings
from .storage import Storage


class CrawlPolicyError(ValueError):
    pass


class _RedirectValidator(HTTPRedirectHandler):
    def __init__(self, policy: "UrlPolicy"):
        self.policy = policy
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.policy.validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ReadableHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.links: list[str] = []
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in {"p", "div", "article", "section", "li", "br", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self.parts.append(data)


def normalize_url(url: str) -> str:
    clean, _fragment = urldefrag(url.strip())
    parsed = urlparse(clean)
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


class UrlPolicy:
    def __init__(self, allow_private_hosts: bool = False):
        self.allow_private_hosts = allow_private_hosts

    def validate(self, url: str) -> str:
        normalized = normalize_url(url)
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            raise CrawlPolicyError("Crawler chỉ hỗ trợ địa chỉ http hoặc https.")
        if not parsed.hostname:
            raise CrawlPolicyError("URL không có tên miền hợp lệ.")
        if parsed.username or parsed.password:
            raise CrawlPolicyError("URL không được chứa thông tin đăng nhập.")
        if not self.allow_private_hosts:
            self._reject_private_host(parsed.hostname)
        return normalized

    @staticmethod
    def _reject_private_host(hostname: str) -> None:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
        except socket.gaierror as error:
            raise CrawlPolicyError(f"Không phân giải được tên miền: {hostname}") from error
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise CrawlPolicyError("Crawler từ chối truy cập địa chỉ mạng nội bộ hoặc dành riêng.")


class RobotsPolicy:
    def __init__(self, settings: Settings, url_policy: UrlPolicy):
        self.settings = settings
        self.url_policy = url_policy
        self._cache: dict[str, RobotFileParser] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(base)
        if parser is None:
            parser = self._load(base)
            with self._lock:
                self._cache[base] = parser
        return parser.can_fetch(self.settings.crawler_user_agent, url)

    def crawl_delay(self, url: str) -> float:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(base)
        delay = parser.crawl_delay(self.settings.crawler_user_agent) if parser else None
        return max(self.settings.crawler_delay_seconds, float(delay or 0))

    def _load(self, base: str) -> RobotFileParser:
        robots_url = f"{base}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            request = Request(robots_url, headers={"User-Agent": self.settings.crawler_user_agent})
            with build_opener(_RedirectValidator(self.url_policy)).open(
                request, timeout=self.settings.crawler_timeout_seconds
            ) as response:
                body = response.read(256_000).decode("utf-8", errors="replace")
            parser.parse(body.splitlines())
        except HTTPError as error:
            if error.code == 404:
                parser.parse(["User-agent: *", "Allow: /"])
            else:
                parser.parse(["User-agent: *", "Disallow: /"])
        except (URLError, TimeoutError, CrawlPolicyError):
            parser.parse(["User-agent: *", "Disallow: /"])
        return parser


@dataclass
class CrawlResult:
    url: str
    title: str
    text: str
    links: list[str]
    content_type: str


class Crawler:
    def __init__(self, storage: Storage, settings: Settings):
        self.storage = storage
        self.settings = settings
        self.url_policy = UrlPolicy(settings.crawler_allow_private_hosts)
        self.robots = RobotsPolicy(settings, self.url_policy)
        self._domain_last_fetch: dict[str, float] = {}

    def enqueue(self, url: str, *, depth: int = 0, discovered_from: str | None = None) -> bool:
        normalized = self.url_policy.validate(url)
        return self.storage.enqueue_url(normalized, depth=depth, discovered_from=discovered_from)

    def enqueue_sitemap(self, url: str, *, max_urls: int = 10_000) -> dict[str, int]:
        counters = {"sitemaps": 0, "queued": 0, "skipped": 0}
        self._enqueue_sitemap_recursive(
            self.url_policy.validate(url),
            max_urls=max(1, min(50_000, max_urls)),
            counters=counters,
            visited=set(),
            depth=0,
        )
        return counters

    def _enqueue_sitemap_recursive(
        self,
        url: str,
        *,
        max_urls: int,
        counters: dict[str, int],
        visited: set[str],
        depth: int,
    ) -> None:
        if url in visited or depth > 2 or counters["queued"] >= max_urls:
            return
        visited.add(url)
        counters["sitemaps"] += 1
        content = self._fetch_sitemap(url)
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as error:
            raise ValueError(f"Sitemap XML không hợp lệ: {url}") from error
        locations = [
            (element.text or "").strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "loc" and (element.text or "").strip()
        ]

        if root.tag.rsplit("}", 1)[-1] == "sitemapindex":
            for location in locations:
                child = self.url_policy.validate(location)
                if self.settings.crawler_same_domain_only and not self._same_domain(url, child):
                    counters["skipped"] += 1
                    continue
                self._enqueue_sitemap_recursive(
                    child,
                    max_urls=max_urls,
                    counters=counters,
                    visited=visited,
                    depth=depth + 1,
                )
            return

        for location in locations:
            if counters["queued"] >= max_urls:
                break
            try:
                page_url = self.url_policy.validate(location)
                if self.settings.crawler_same_domain_only and not self._same_domain(url, page_url):
                    counters["skipped"] += 1
                    continue
                if self.storage.enqueue_url(page_url, discovered_from=url):
                    counters["queued"] += 1
            except CrawlPolicyError:
                counters["skipped"] += 1

    def crawl_queued(self, *, max_pages: int = 20, max_depth: int = 1) -> dict[str, int]:
        counters = {
            "processed": 0,
            "indexed": 0,
            "skipped": 0,
            "retryScheduled": 0,
            "failed": 0,
            "discovered": 0,
        }
        while counters["processed"] < max_pages:
            item = self.storage.claim_next_url()
            if not item:
                break
            counters["processed"] += 1
            try:
                if item["depth"] > max_depth:
                    self.storage.finish_crawl(item["id"], "skipped", "Vượt quá độ sâu cho phép.")
                    counters["skipped"] += 1
                    continue
                if not self.robots.allowed(item["url"]):
                    self.storage.finish_crawl(item["id"], "skipped", "robots.txt không cho phép thu thập.")
                    counters["skipped"] += 1
                    continue

                result = self._fetch(item["url"])
                if len(result.text.split()) < 12:
                    self.storage.finish_crawl(item["id"], "skipped", "Nội dung quá ngắn để lập chỉ mục.")
                    counters["skipped"] += 1
                    continue
                self.storage.upsert_source(
                    url=result.url,
                    title=result.title or result.url,
                    text_content=result.text,
                    source_type="website",
                    metadata={"contentType": result.content_type, "crawler": "MinhChungResearchBot"},
                )
                counters["indexed"] += 1

                if item["depth"] < max_depth:
                    for link in result.links:
                        try:
                            if self.settings.crawler_same_domain_only and not self._same_domain(result.url, link):
                                continue
                            if self.enqueue(link, depth=item["depth"] + 1, discovered_from=result.url):
                                counters["discovered"] += 1
                        except CrawlPolicyError:
                            continue
                self.storage.finish_crawl(item["id"], "indexed")
            except (HTTPError, URLError, TimeoutError) as error:
                if self._retryable_error(error):
                    status = self.storage.schedule_crawl_retry(
                        item["id"],
                        error=str(error),
                        max_attempts=self.settings.crawler_max_attempts,
                        retry_base_seconds=self.settings.crawler_retry_base_seconds,
                    )
                    counters["retryScheduled" if status == "retry_wait" else "failed"] += 1
                else:
                    self.storage.finish_crawl(item["id"], "failed", str(error)[:500])
                    counters["failed"] += 1
            except (CrawlPolicyError, ValueError) as error:
                self.storage.finish_crawl(item["id"], "failed", str(error)[:500])
                counters["failed"] += 1
        return counters

    @staticmethod
    def _same_domain(parent_url: str, candidate_url: str) -> bool:
        return urlparse(parent_url).hostname == urlparse(candidate_url).hostname

    @staticmethod
    def _retryable_error(error: HTTPError | URLError | TimeoutError) -> bool:
        if isinstance(error, HTTPError):
            return error.code in {408, 425, 429} or 500 <= error.code < 600
        return True

    def _fetch(self, url: str) -> CrawlResult:
        normalized = self.url_policy.validate(url)
        self._wait_for_domain(normalized)
        request = Request(normalized, headers={"User-Agent": self.settings.crawler_user_agent})
        with build_opener(_RedirectValidator(self.url_policy)).open(
            request, timeout=self.settings.crawler_timeout_seconds
        ) as response:
            final_url = self.url_policy.validate(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError(f"Loại nội dung chưa hỗ trợ: {content_type}")
            content = response.read(self.settings.crawler_max_bytes + 1)
            if len(content) > self.settings.crawler_max_bytes:
                raise ValueError("Trang vượt quá giới hạn dung lượng của crawler.")
            charset = response.headers.get_content_charset() or "utf-8"
            body = content.decode(charset, errors="replace")

        if content_type == "text/plain":
            return CrawlResult(final_url, final_url, body, [], content_type)

        parser = _ReadableHtmlParser()
        parser.feed(body)
        links = [urljoin(final_url, href) for href in parser.links]
        text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        return CrawlResult(final_url, parser.title.strip(), text, links, content_type)

    def _fetch_sitemap(self, url: str) -> bytes:
        normalized = self.url_policy.validate(url)
        self._wait_for_domain(normalized)
        request = Request(normalized, headers={"User-Agent": self.settings.crawler_user_agent})
        with build_opener(_RedirectValidator(self.url_policy)).open(
            request, timeout=self.settings.crawler_timeout_seconds
        ) as response:
            content = response.read(self.settings.crawler_sitemap_max_bytes + 1)
            if len(content) > self.settings.crawler_sitemap_max_bytes:
                raise ValueError("Sitemap vượt quá giới hạn dung lượng.")
            if normalized.endswith(".gz") or response.headers.get("Content-Encoding") == "gzip":
                content = gzip.decompress(content)
                if len(content) > self.settings.crawler_sitemap_max_bytes:
                    raise ValueError("Sitemap sau giải nén vượt quá giới hạn dung lượng.")
            return content

    def _wait_for_domain(self, url: str) -> None:
        domain = urlparse(url).netloc.lower()
        delay = self.robots.crawl_delay(url)
        elapsed = time.monotonic() - self._domain_last_fetch.get(domain, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._domain_last_fetch[domain] = time.monotonic()


class CrawlRunner:
    def __init__(self, crawler: Crawler):
        self.crawler = crawler
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {"running": False, "lastResult": None, "lastError": None}

    def start(self, *, max_pages: int = 20, max_depth: int = 1) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._state = {"running": True, "lastResult": None, "lastError": None}
            self._thread = threading.Thread(
                target=self._run,
                kwargs={"max_pages": max_pages, "max_depth": max_depth},
                daemon=True,
            )
            self._thread.start()
            return True

    def _run(self, *, max_pages: int, max_depth: int) -> None:
        try:
            result = self.crawler.crawl_queued(max_pages=max_pages, max_depth=max_depth)
            with self._lock:
                self._state = {"running": False, "lastResult": result, "lastError": None}
        except Exception as error:  # pragma: no cover - defensive boundary for a worker thread
            with self._lock:
                self._state = {"running": False, "lastResult": None, "lastError": str(error)}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)
