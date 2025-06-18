# GIDBOT/bot/github_tool_client.py
import os
import time
import random
from github import Github, GithubException
from typing import List

class GithubTool:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN environment variable not set.")
        self.client = Github(self.token)

    def fetch_github_prs(self, repo_name: str, max_results: int = 50, retries: int = 3) -> List[dict]:
        """
        Fetch recent pull requests from a GitHub repository.

        Args:
            repo_name (str): The name of the repository (e.g., 'your-org/your-repo').
            max_results (int): Maximum number of PRs to fetch.
            retries (int): Number of retries on rate limit.

        Returns:
            List of PRs as dictionaries.
        """
        print(f"Fetching recent PRs from repo: {repo_name}")
        for attempt in range(retries):
            try:
                repo = self.client.get_repo(repo_name)
                pulls = repo.get_pulls(state='all', sort='updated', direction='desc')

                all_prs = []
                for pr in pulls[:max_results]:
                    pr_data = {
                        "number": pr.number,
                        "title": pr.title,
                        "state": pr.state, # 'open', 'closed'
                        "user": pr.user.login,
                        "body": pr.body if pr.body else "",
                        "url": pr.html_url,
                        "created_at": pr.created_at.isoformat(),
                        "updated_at": pr.updated_at.isoformat(),
                        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    }
                    all_prs.append(pr_data)
                
                print(f"Successfully fetched {len(all_prs)} PRs from {repo_name}")
                return all_prs

            except GithubException as e:
                if e.status == 403 and 'rate limit' in str(e.data):
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    print(f"GitHub rate limit hit. Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                else:
                    raise e
        
        raise Exception("Exceeded GitHub API rate limit retries")