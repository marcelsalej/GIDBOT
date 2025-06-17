import os
import time
import random
from jira import JIRA
from typing import List, Optional

class JiraTool:
    def __init__(self):
        self.base_url = os.getenv("JIRA_BASE_URL")
        self.auth = (os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
        self.client = self.create_jira_client()

    def create_jira_client(self) -> JIRA:
        options = {"server": self.base_url}
        email, api_token = self.auth
        return JIRA(options, basic_auth=(email, api_token))

    def fetch_jira_issues(self, jql: str, max_results: int = 50, retries: int = 3) -> List:
        """
        Fetch Jira issues with pagination, retry on rate limits.

        Args:
            jql (str): JQL query string.
            max_results (int): Maximum number of issues to fetch per request.
            retries (int): Number of retries on rate limit.

        Returns:
            List of Jira issues.
        """
        print(f"JQL is: {jql}")
        all_issues = []
        start_at = 0

        while True:
            attempt = 0
            while attempt < retries:
                try:
                    issues = self.client.search_issues(jql, startAt=start_at, maxResults=max_results)
                    break
                except Exception as e:
                    if "429" in str(e):
                        wait_time = 2 ** attempt + random.uniform(0, 1)
                        print(f"Rate limit hit on Jira API. Retrying in {wait_time:.2f}s...")
                        time.sleep(wait_time)
                        attempt += 1
                    else:
                        raise

            if attempt == retries:
                raise Exception("Exceeded Jira API rate limit retries")

            all_issues.extend(issues)
            if len(issues) < max_results:
                # No more issues to fetch
                break
            start_at += max_results

        return all_issues

    def list_projects(self):
        projects = self.client.projects()
        print("Available Projects:")
        for project in projects:
            print(f"{project.key} - {project.name}")