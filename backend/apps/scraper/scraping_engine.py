"""
Web scraping engine using Crawl4AI and Playwright.
"""
import logging
import time
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from django.conf import settings
from apps.core.utils import generate_unique_hash, extract_domain, RateLimiter

logger = logging.getLogger(__name__)


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
        max_retries: int = 3
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
            return None

        # Rate limiting
        domain = extract_domain(url)
        if domain:
            self.rate_limiter.wait_if_needed(domain)

        for attempt in range(self.max_retries):
            try:
                if self.use_js_rendering:
                    return await self._fetch_with_browser(url)
                else:
                    return await self._fetch_with_requests(url)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"All attempts failed for {url}")
                    return None

        return None

    async def _fetch_with_requests(self, url: str) -> str:
        """
        Fetch page using requests library.

        Args:
            url: URL to fetch

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
            allow_redirects=True
        )
        response.raise_for_status()
        return response.text

    async def _fetch_with_browser(self, url: str) -> str:
        """
        Fetch page using Playwright browser.

        Args:
            url: URL to fetch

        Returns:
            Page HTML content
        """
        if not self.browser:
            await self.initialize_browser()

        page = await self.browser.new_page()
        page.set_default_timeout(self.timeout * 1000)

        try:
            await page.goto(url, wait_until='networkidle')
            # Wait for any dynamic content
            await page.wait_for_timeout(1000)
            content = await page.content()
            return content
        finally:
            await page.close()

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

    async def scrape_url(
        self,
        url: str,
        selectors: Dict[str, Any],
        pagination_config: Optional[Dict[str, Any]] = None,
        max_pages: int = 100
    ) -> Dict[str, Any]:
        """
        Scrape a URL with pagination support.

        Args:
            url: Starting URL
            selectors: Data extraction selectors
            pagination_config: Pagination configuration
            max_pages: Maximum number of pages to scrape

        Returns:
            Dictionary with scraped items and stats
        """
        all_items = []
        pages_visited = 0
        urls_to_visit = [url]
        visited_urls = set()

        try:
            while urls_to_visit and pages_visited < max_pages:
                current_url = urls_to_visit.pop(0)

                if current_url in visited_urls:
                    continue

                logger.info(f"Scraping: {current_url}")

                # Fetch page
                html = await self.fetch_page(current_url)
                if not html:
                    continue

                visited_urls.add(current_url)
                pages_visited += 1

                # Extract data
                items = self.extract_data(html, selectors, current_url)
                all_items.extend(items)

                logger.info(f"Extracted {len(items)} items from {current_url}")

                # Find pagination links
                if pagination_config and pages_visited < max_pages:
                    pagination_links = self.find_pagination_links(
                        html,
                        pagination_config,
                        current_url,
                        current_url
                    )
                    urls_to_visit.extend(pagination_links)

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
