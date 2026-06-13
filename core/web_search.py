import logging
from ddgs import DDGS

logger = logging.getLogger(__name__)

def perform_web_search(query: str, max_results: int = 3) -> str:
    """
    Searches the web using DuckDuckGo and uses Scrapling to extract text content
    from the top results. Returns a formatted context string.
    """
    try:
        from scrapling import Fetcher
    except ImportError:
        logger.warning("Scrapling not installed, web scraping might fail.")
        Fetcher = None

    context_parts = []
    
    try:
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            return "No web search results found."

        if Fetcher:
            fetcher = Fetcher(auto_match=False)
        else:
            fetcher = None

        for idx, res in enumerate(results):
            title = res.get('title', 'Unknown Title')
            href = res.get('href', '')
            snippet = res.get('body', '')
            
            context_parts.append(f"Source [{idx+1}]: {title}\nURL: {href}")
            
            page_text = ""
            if href:
                try:
                    if fetcher:
                        page = fetcher.get(href)
                        if hasattr(page, 'text_content'):
                            page_text = page.text_content()
                        elif hasattr(page, 'text'):
                            page_text = page.text
                    else:
                        import requests
                        from bs4 import BeautifulSoup
                        response = requests.get(href, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.content, 'html.parser')
                            page_text = soup.get_text(separator=' ', strip=True)
                        
                    if len(page_text) > 2000:
                        page_text = page_text[:2000] + "... [truncated]"
                except Exception as e:
                    logger.debug(f"Failed to scrape {href}: {e}")
            
            if not page_text:
                page_text = snippet

            context_parts.append(f"Content:\n{page_text}\n")
            
        return "=== WEB SEARCH RESULTS ===\n" + "\n".join(context_parts) + "\n===========================\n"
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Web search failed: {e}"
