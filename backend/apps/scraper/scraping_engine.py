"""
Web scraping engine using Crawl4AI and Playwright.
"""
import logging
import time
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from django.conf import settings
from apps.core.utils import generate_unique_hash, extract_domain, RateLimiter

logger = logging.getLogger(__name__)

# Hard ceiling so an "all pages" request (or a misbehaving next-link loop) can never
# run away. Tune via settings if needed.
SAFETY_MAX_PAGES = 200

# Anchor text that commonly denotes the "next page" control.
_NEXT_TEXTS = {'next', 'next page', 'next »', '›', '»', '→', 'older', 'older posts'}


class ScrapingEngine:
    """
    Main scraping engine using Crawl4AI and Playwright.
    """

    def __init__(
        self,
        use_js_rendering: bool = False,
        respect_robots_txt: bool = True,
        rate_limit: float = 1.0,
        user_agent: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        proxies: Optional[List[str]] = None
    ):
        """
        Initialize scraping engine.

        Args:
            use_js_rendering: Whether to use headless browser for JS rendering
            respect_robots_txt: Whether to respect robots.txt
            rate_limit: Requests per second
            user_agent: Custom user agent string
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            proxies: Optional rotating proxy pool (URLs). Falls back to the global
                SCRAPER_CONFIG['PROXY_URLS'] when not given.
        """
        self.use_js_rendering = use_js_rendering
        self.respect_robots_txt = respect_robots_txt
        self.rate_limiter = RateLimiter(rate=rate_limit)
        self.user_agent = user_agent or settings.SCRAPER_CONFIG['DEFAULT_USER_AGENT']
        self.timeout = timeout
        self.max_retries = max_retries
        self.robots_cache = {}
        self.browser = None
        self.playwright = None
        # URLs skipped because robots.txt disallowed them; lets callers tell a
        # robots-blocked run apart from one that simply found no data.
        self.blocked_urls = []
        # Rotating proxy pool + per-proxy cooldown (epoch until which it's parked
        # after a failure / 403 / 429). Empty pool == direct connection.
        self.proxies = list(proxies) if proxies else list(
            settings.SCRAPER_CONFIG.get('PROXY_URLS', [])
        )
        self._proxy_idx = 0
        self._proxy_cooldown: Dict[str, float] = {}

    async def initialize_browser(self):
        """Initialize Playwright browser if needed."""
        if self.use_js_rendering and self.browser is None:
            try:
                from playwright.async_api import async_playwright
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=settings.SCRAPER_CONFIG['HEADLESS_BROWSER']
                )
                logger.info("Playwright browser initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Playwright browser: {e}")
                raise

    async def close_browser(self):
        """Close Playwright browser."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
            logger.info("Playwright browser closed")

    # ----- Proxy pool ------------------------------------------------------

    def _pick_proxy(self) -> Optional[str]:
        """Round-robin the next proxy that isn't in cooldown, or None (direct)."""
        if not self.proxies:
            return None
        now = time.time()
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self._proxy_idx % len(self.proxies)]
            self._proxy_idx += 1
            if self._proxy_cooldown.get(proxy, 0) <= now:
                return proxy
        # Every proxy is cooling down — use the soonest-available one anyway.
        return min(self.proxies, key=lambda p: self._proxy_cooldown.get(p, 0))

    def _cooldown_proxy(self, proxy: Optional[str], seconds: int = 300) -> None:
        """Park a proxy for ``seconds`` after a failure / block."""
        if proxy:
            self._proxy_cooldown[proxy] = time.time() + seconds
            logger.warning(f"Proxy parked for {seconds}s after failure: {self._mask(proxy)}")

    @staticmethod
    def _mask(proxy: str) -> str:
        """Hide credentials when logging a proxy URL."""
        try:
            p = urlparse(proxy)
            host = p.hostname or ''
            port = f":{p.port}" if p.port else ''
            return f"{p.scheme}://{host}{port}"
        except Exception:
            return '<proxy>'

    @staticmethod
    def _playwright_proxy(proxy: Optional[str]) -> Optional[Dict[str, str]]:
        """Convert a proxy URL into Playwright's {server, username, password} form."""
        if not proxy:
            return None
        p = urlparse(proxy)
        server = f"{p.scheme}://{p.hostname}{':' + str(p.port) if p.port else ''}"
        out = {'server': server}
        if p.username:
            out['username'] = p.username
        if p.password:
            out['password'] = p.password
        return out

    def check_robots_txt(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.

        Args:
            url: URL to check

        Returns:
            True if allowed, False otherwise
        """
        if not self.respect_robots_txt:
            return True

        domain = extract_domain(url)
        if not domain:
            return True

        # Check cache
        if domain in self.robots_cache:
            rp = self.robots_cache[domain]
        else:
            # Fetch robots.txt
            rp = RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            rp.set_url(robots_url)
            try:
                rp.read()
                self.robots_cache[domain] = rp
            except Exception as e:
                logger.warning(f"Failed to fetch robots.txt for {domain}: {e}")
                return True  # Allow if we can't fetch robots.txt

        return rp.can_fetch(self.user_agent, url)

    async def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch page content.

        Args:
            url: URL to fetch

        Returns:
            Page HTML content or None if failed
        """
        # Check robots.txt
        if not self.check_robots_txt(url):
            logger.warning(f"URL blocked by robots.txt: {url}")
            if url not in self.blocked_urls:
                self.blocked_urls.append(url)
            return None

        # Rate limiting
        domain = extract_domain(url)
        if domain:
            self.rate_limiter.wait_if_needed(domain)

        for attempt in range(self.max_retries):
            # Rotate to the next healthy proxy for each attempt (None = direct).
            proxy = self._pick_proxy()
            try:
                if self.use_js_rendering:
                    return await self._fetch_with_browser(url, proxy)
                else:
                    return await self._fetch_with_requests(url, proxy)
            except Exception as e:
                # Park the proxy on a block/forbidden/rate-limit so the next attempt
                # rotates away from it.
                if proxy and self._is_block_error(e):
                    self._cooldown_proxy(proxy)
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"All attempts failed for {url}")
                    return None

        return None

    @staticmethod
    def _is_block_error(exc: Exception) -> bool:
        """True if the exception looks like an IP/proxy block (403/429/connection)."""
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in (403, 407, 429):
            return True
        text = str(exc).lower()
        return any(s in text for s in ('403', '429', 'proxy', 'timeout', 'connection'))

    async def _fetch_with_requests(self, url: str, proxy: Optional[str] = None) -> str:
        """
        Fetch page using requests library.

        Args:
            url: URL to fetch
            proxy: Optional proxy URL to route this request through

        Returns:
            Page HTML content
        """
        import requests

        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=True,
            proxies={'http': proxy, 'https': proxy} if proxy else None
        )
        response.raise_for_status()
        return response.text

    async def _fetch_with_browser(self, url: str, proxy: Optional[str] = None) -> str:
        """
        Fetch page using Playwright browser.

        Args:
            url: URL to fetch
            proxy: Optional proxy URL; applied at the browser context so it can
                rotate per request without relaunching the browser.

        Returns:
            Page HTML content
        """
        if not self.browser:
            await self.initialize_browser()

        # Per-context proxy lets each fetch use a different pool member.
        context = await self.browser.new_context(proxy=self._playwright_proxy(proxy))
        page = await context.new_page()
        page.set_default_timeout(self.timeout * 1000)

        try:
            await page.goto(url, wait_until='networkidle')
            # Wait for any dynamic content
            await page.wait_for_timeout(1000)
            content = await page.content()
            return content
        finally:
            await page.close()
            await context.close()

    def extract_data(
        self,
        html: str,
        selectors: Dict[str, Any],
        base_url: str
    ) -> List[Dict[str, Any]]:
        """
        Extract data from HTML using CSS selectors.

        Args:
            html: HTML content
            selectors: Dictionary of field selectors
            base_url: Base URL for resolving relative URLs

        Returns:
            List of extracted data items
        """
        soup = BeautifulSoup(html, 'lxml')
        items = []

        # Get container selector (for lists/tables)
        container_selector = selectors.get('container')
        if container_selector:
            containers = soup.select(container_selector)
        else:
            containers = [soup]  # Use entire page as single container

        for container in containers:
            item = {}
            has_data = False

            for field_name, field_config in selectors.get('fields', {}).items():
                selector = field_config.get('selector')
                attr = field_config.get('attr', 'text')
                field_type = field_config.get('type', 'string')

                if not selector:
                    continue

                element = container.select_one(selector)
                if element:
                    # Extract value
                    if attr == 'text':
                        value = element.get_text(strip=True)
                    elif attr == 'html':
                        value = str(element)
                    else:
                        value = element.get(attr, '')

                    # Resolve relative URLs
                    if field_type == 'url' and value:
                        value = urljoin(base_url, value)

                    # Type conversion
                    if field_type == 'number' and value:
                        try:
                            value = float(value.replace(',', ''))
                        except ValueError:
                            pass

                    item[field_name] = value
                    has_data = True
                else:
                    item[field_name] = None

            if has_data:
                items.append(item)

        return items

    def find_pagination_links(
        self,
        html: str,
        pagination_config: Dict[str, Any],
        base_url: str,
        current_url: str
    ) -> List[str]:
        """
        Find pagination links.

        Args:
            html: HTML content
            pagination_config: Pagination configuration
            base_url: Base URL for resolving relative URLs
            current_url: Current page URL

        Returns:
            List of pagination URLs
        """
        soup = BeautifulSoup(html, 'lxml')
        links = []

        pagination_type = pagination_config.get('type')

        if pagination_type == 'selector':
            # Find next page link using selector
            next_selector = pagination_config.get('next_selector')
            if next_selector:
                next_link = soup.select_one(next_selector)
                if next_link:
                    href = next_link.get('href')
                    if href:
                        links.append(urljoin(base_url, href))

        elif pagination_type == 'url_pattern':
            # Generate URLs using pattern
            pattern = pagination_config.get('pattern')
            start = pagination_config.get('start', 1)
            end = pagination_config.get('end', 10)

            for page_num in range(start, end + 1):
                url = pattern.replace('{page}', str(page_num))
                if url != current_url:
                    links.append(url)

        return links

    def discover_next_url(
        self,
        html: str,
        current_url: str,
        pagination_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Find the next page's URL with no user-supplied selector.

        Order of attempts:
          1. An explicit ``pagination_config`` (back-compat / power users).
          2. ``rel="next"`` on a <link> or <a> (the semantic, most reliable signal).
          3. An anchor whose visible text / aria-label reads like a "next" control.
          4. Incrementing a ``page`` (or ``p``/``pn``) query parameter on the URL.

        Returns an absolute URL, or ``None`` when no next page can be inferred.
        """
        if pagination_config:
            links = self.find_pagination_links(html, pagination_config, current_url, current_url)
            return links[0] if links else None

        soup = BeautifulSoup(html, 'lxml')

        # 2. rel="next"
        rel_next = soup.select_one('link[rel~="next"], a[rel~="next"]')
        if rel_next and rel_next.get('href'):
            return urljoin(current_url, rel_next['href'])

        # 3. Anchor that looks like a "next" control.
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            label = (a.get_text() or '').strip().lower()
            aria = (a.get('aria-label') or '').strip().lower()
            if label in _NEXT_TEXTS or 'next' in aria:
                return urljoin(current_url, href)

        # 4. Increment a page-number query parameter.
        return self._increment_page_param(current_url)

    @staticmethod
    def _increment_page_param(url: str) -> Optional[str]:
        """Return ``url`` with its page parameter bumped by one (page 1 assumed absent)."""
        parsed = urlparse(url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        page_keys = ('page', 'pageno', 'pagenumber', 'pn', 'p')
        new_params = []
        found = False
        for k, v in params:
            if k.lower() in page_keys and v.isdigit():
                new_params.append((k, str(int(v) + 1)))
                found = True
            else:
                new_params.append((k, v))
        if not found:
            # No explicit page param -> page 1 is implicit, so the next page is 2.
            new_params.append(('page', '2'))
        new_query = urlencode(new_params)
        return parsed._replace(query=new_query).geturl()

    async def scrape_url(
        self,
        url: str,
        selectors: Dict[str, Any],
        pagination_config: Optional[Dict[str, Any]] = None,
        max_pages: int = 1
    ) -> Dict[str, Any]:
        """
        Scrape a URL, following pagination across up to ``max_pages`` pages.

        Args:
            url: Starting URL
            selectors: Data extraction selectors
            pagination_config: Optional explicit pagination config (else auto-detect)
            max_pages: Page budget. ``1`` = single page (no pagination); ``N`` = up to
                N pages; ``0`` = all pages (bounded by ``SAFETY_MAX_PAGES``).

        Returns:
            Dictionary with scraped items and stats
        """
        # 0 ("all") -> safety ceiling; anything above the ceiling is clamped to it.
        effective_max = SAFETY_MAX_PAGES if max_pages in (0, None) else min(max_pages, SAFETY_MAX_PAGES)

        all_items = []
        pages_visited = 0
        current_url: Optional[str] = url
        visited_urls = set()

        try:
            while current_url and pages_visited < effective_max:
                if current_url in visited_urls:
                    break  # looped back on ourselves -> stop

                logger.info(f"Scraping: {current_url}")
                html = await self.fetch_page(current_url)
                if not html:
                    break

                visited_urls.add(current_url)
                pages_visited += 1

                items = self.extract_data(html, selectors, current_url)
                logger.info(f"Extracted {len(items)} items from {current_url}")

                # End-of-list guard: a follow-on page with no rows means we've run past
                # the last real page (e.g. ?page=99). Don't append, don't continue.
                if pages_visited > 1 and not items:
                    logger.info(f"No items on {current_url}; stopping pagination")
                    break
                all_items.extend(items)

                # Discover the next page only if we still have budget left.
                if pages_visited < effective_max:
                    current_url = self.discover_next_url(html, current_url, pagination_config)
                else:
                    current_url = None

            return {
                'items': all_items,
                'pages_visited': pages_visited,
                'urls_visited': list(visited_urls)
            }

        finally:
            if self.use_js_rendering:
                await self.close_browser()


class SelectorTester:
    """
    Test selectors on a page and return sample data.
    """

    @staticmethod
    async def fetch_html(url: str, use_js_rendering: bool = False) -> Optional[str]:
        """Fetch a page's HTML (ignoring robots.txt — this is interactive testing)."""
        engine = ScrapingEngine(
            use_js_rendering=use_js_rendering,
            respect_robots_txt=False
        )
        try:
            return await engine.fetch_page(url)
        finally:
            if use_js_rendering:
                await engine.close_browser()

    @staticmethod
    def sample_from_html(html: str, selectors: Dict[str, Any], url: str) -> Dict[str, Any]:
        """Extract sample rows from already-fetched HTML (no network)."""
        engine = ScrapingEngine(respect_robots_txt=False)
        items = engine.extract_data(html, selectors, url)
        return {
            'success': True,
            'items': items[:20],
            'total_found': len(items),
            'selectors_tested': len(selectors.get('fields', {})),
        }

    @staticmethod
    async def test_selectors(
        url: str,
        selectors: Dict[str, Any],
        use_js_rendering: bool = False
    ) -> Dict[str, Any]:
        """
        Test selectors on a URL and return sample data.

        Args:
            url: URL to test
            selectors: Selectors to test
            use_js_rendering: Whether to use browser

        Returns:
            Dictionary with sample items and validation results
        """
        engine = ScrapingEngine(
            use_js_rendering=use_js_rendering,
            respect_robots_txt=False  # Don't check robots.txt when testing
        )

        try:
            html = await engine.fetch_page(url)
            if not html:
                return {
                    'success': False,
                    'error': 'Failed to fetch page',
                    'items': []
                }

            items = engine.extract_data(html, selectors, url)

            return {
                'success': True,
                'items': items[:20],  # Return first 20 items
                'total_found': len(items),
                'selectors_tested': len(selectors.get('fields', {}))
            }

        except Exception as e:
            logger.error(f"Error testing selectors: {e}")
            return {
                'success': False,
                'error': str(e),
                'items': []
            }
        finally:
            await engine.close_browser()
