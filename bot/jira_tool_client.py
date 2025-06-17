import os
from jira import JIRA

class JiraTool:
    def __init__(self):
        self.base_url = os.getenv("JIRA_BASE_URL")
        self.auth = (os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))

    def create_jira_client(self):
        server_url = self.base_url
        email, api_token = self.auth

        options = {"server": server_url}
        return JIRA(options, basic_auth=(email, api_token))

    def fetch_jira_issues(self, jql: str):
        client = self.create_jira_client()
        issues = client.search_issues(jql)
        return [
            issue
            for issue in issues
        ]
        
    def list_projects(self):
        client = self.create_jira_client()
        projects = client.projects()
        print("Available Projects:")
        for project in projects:
            print(f"{project.key} - {project.name}")