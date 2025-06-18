# bot/jira_tool_client.py
import os
import time
import random
from jira import JIRA, JIRAError
from typing import List, Optional, Dict, Any

class JiraTool:
    def __init__(self):
        self.base_url = os.getenv("JIRA_BASE_URL")
        self.auth = (os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
        self.client = self.create_jira_client()
        
        self.epic_link_field_id = self._find_epic_link_field_id()
        if self.epic_link_field_id:
            print(f"[INFO] Successfully discovered Jira Epic Link Field ID: {self.epic_link_field_id}")
        else:
            print("[WARN] Could not discover Epic Link Field ID. Epic relationships may not be available.")

    def create_jira_client(self) -> JIRA:
        options = {"server": self.base_url}
        email, api_token = self.auth
        return JIRA(options, basic_auth=(email, api_token))

    def _find_epic_link_field_id(self) -> Optional[str]:
        """
        Queries the Jira API to find the custom field ID for 'Epic Link'.
        This avoids needing admin permissions to find the ID manually.
        """
        try:
            env_id = os.getenv("JIRA_EPIC_LINK_FIELD_ID")
            if env_id:
                print(f"[INFO] Using JIRA_EPIC_LINK_FIELD_ID from environment: {env_id}")
                return env_id

            print("[INFO] JIRA_EPIC_LINK_FIELD_ID not set. Attempting to discover it automatically...", flush=True)
            all_fields = self.client.fields()
            
            for field in all_fields:
                if field['name'].lower() == 'epic link':
                    return field['id']
            
            for field in all_fields:
                if field['name'].lower() == 'parent' and 'epic' in str(field.get('schema', {}).get('custom', '')).lower():
                    return field['id']

        except JIRAError as e:
            print(f"[ERROR] A Jira API error occurred while trying to discover fields: {e.text}")
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred during field discovery: {e}")
            
        return None

    def _get_parent_info(self, issue: Any) -> Optional[Dict[str, str]]:
        """
        Extracts parent information for sub-tasks or issues linked to an epic.
        """
        parent_issue = None
        if hasattr(issue.fields, 'parent'):
            parent_issue = issue.fields.parent
        elif self.epic_link_field_id and hasattr(issue.fields, self.epic_link_field_id):
            epic_key = getattr(issue.fields, self.epic_link_field_id)
            if epic_key:
                try:
                    parent_issue = self.client.issue(epic_key)
                except JIRAError as e:
                    print(f"[WARN] Could not fetch details for Epic {epic_key}: {e.text}")
                    return {"key": epic_key, "summary": "Epic (details unavailable)", "status": "Unknown", "issuetype": "Epic"}
        
        if parent_issue:
            return {
                "key": parent_issue.key,
                "summary": parent_issue.fields.summary,
                "status": parent_issue.fields.status.name,
                "issuetype": parent_issue.fields.issuetype.name
            }
        
        return None

    def fetch_jira_issues_by_project(self, project_keys: List[str], retries: int = 3) -> List[dict]:
        """
        Fetch all Jira issues for a list of projects, handling pagination and retries for each.
        This is more robust against single large query limits.
        """
        all_project_issues = []
        
        for project_key in project_keys:
            print(f"--- Starting fetch for project: {project_key} ---")
            jql = f'project = "{project_key}" ORDER BY created DESC'
            
            attempt = 0
            while attempt < retries:
                try:
                    print(f"Attempting to fetch all issues for project {project_key}...", flush=True)
                    
                    fields_to_fetch = "*all"
                    if self.epic_link_field_id:
                        fields_to_fetch += f", {self.epic_link_field_id}"

                    # Let the library handle pagination for this single project query
                    issues = self.client.search_issues(
                        jql_str=jql,
                        maxResults=None, 
                        fields=fields_to_fetch
                    )
                    
                    print(f"Successfully fetched {len(issues)} issues for project {project_key}.", flush=True)
                    
                    # Process and add issues to the main list
                    for issue in issues:
                        issue_data = {
                            "key": issue.key,
                            "summary": issue.fields.summary,
                            "status": issue.fields.status.name,
                            "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "unassigned",
                            "description": issue.fields.description,
                            "url": f"{self.base_url}/browse/{issue.key}",
                            "updated": issue.fields.updated,
                            "parent": self._get_parent_info(issue),
                            "raw_data": issue.raw
                        }
                        all_project_issues.append(issue_data)
                    
                    break  # Success for this project, move to the next one

                except JIRAError as e:
                    if e.status_code == 429 or "rate limit" in str(e).lower():
                        wait_time = 2 ** attempt + random.uniform(0, 1)
                        print(f"Rate limit hit on project {project_key}. Retrying in {wait_time:.2f}s...")
                        time.sleep(wait_time)
                        attempt += 1
                    else:
                        print(f"A Jira API error occurred on project {project_key}: {e.text}")
                        # Break the retry loop for this project and move to the next
                        break 
                except Exception as e:
                    print(f"An unexpected error occurred on project {project_key}: {e}")
                    # Break the retry loop for this project and move to the next
                    break

            if attempt == retries:
                print(f"Exceeded max retries for project {project_key}. Skipping.")
        print(f"Successfully fetched all {len(all_project_issues)} issues.", flush=True)
        return all_project_issues