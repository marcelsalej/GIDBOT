"""
Tool wrapper for Confluence API access
"""

import requests
import os

class ConfluenceTool:
    def __init__(self):
        self.base_url = os.getenv("CONFLUENCE_BASE_URL")
        self.auth = (os.getenv("CONFLUENCE_EMAIL"), os.getenv("CONFLUENCE_API_TOKEN"))

    def run(self, query: str) -> str:
        url = f"{self.base_url}/wiki/rest/api/content/search?cql=text~'{query}'"
        response = requests.get(url, auth=self.auth)
        if response.ok:
            pages = response.json().get("results", [])
            return f"Found {len(pages)} Confluence pages."
        return "Failed to retrieve Confluence data"
