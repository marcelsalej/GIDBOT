"""
Tool wrapper for Confluence API access
"""
import os
from atlassian import Confluence
from bs4 import BeautifulSoup # To clean HTML from Confluence pages

class ConfluenceTool:
    def __init__(self):
        self.base_url = os.getenv("CONFLUENCE_BASE_URL")
        self.email = os.getenv("CONFLUENCE_EMAIL")
        self.api_token = os.getenv("CONFLUENCE_API_TOKEN")

        if not all([self.base_url, self.email, self.api_token]):
            raise ValueError("CONFLUENCE environment variables are not fully set.")

        self.client = Confluence(
            url=self.base_url,
            username=self.email,
            password=self.api_token,
            cloud=True # Set to True if you are using Atlassian Cloud
        )

    def _clean_html(self, html_content: str) -> str:
        """Strips HTML tags to get clean text."""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    def fetch_confluence_pages(self, space_key: str, limit: int = 50) -> list[dict]:
        """
        Fetches pages from a given Confluence space.

        Args:
            space_key (str): The key of the Confluence space (e.g., 'Engineering').
            limit (int): The maximum number of pages to fetch.

        Returns:
            A list of dictionaries, each representing a page with its content.
        """
        print(f"Fetching recent pages from Confluence space: {space_key}")
        try:
            pages = self.client.get_all_pages_from_space(space_key, limit=limit)
            
            detailed_pages = []
            for page in pages:
                page_id = page['id']
                # Fetch page content, as it's not included in the list view
                page_content = self.client.get_page_by_id(page_id, expand='body.storage')
                
                raw_body = page_content.get('body', {}).get('storage', {}).get('value', '')
                clean_body = self._clean_html(raw_body)
                
                page_data = {
                    "id": page_id,
                    "title": page['title'],
                    "body": clean_body,
                    "url": self.base_url + page['_links']['webui']
                }
                detailed_pages.append(page_data)
            
            print(f"Successfully fetched {len(detailed_pages)} pages from Confluence space '{space_key}'")
            return detailed_pages

        except Exception as e:
            print(f"Error fetching Confluence pages: {e}")
            # Depending on the library version, error details might be in e.response
            return []

    def run(self, query: str) -> str:
        # This original 'run' method can be kept if you ever want to use it
        # for a real-time agent, but it's not used by our RAG system.
        results = self.client.search(cql=f"text~'{query}'")
        return f"Found {len(results)} Confluence pages."