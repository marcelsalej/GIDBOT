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
        
        # --- NEW: Automatically discover the Epic Link field ID ---
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
            # First, check if the ID was provided in the environment as an override
            env_id = os.getenv("JIRA_EPIC_LINK_FIELD_ID")
            if env_id:
                print(f"[INFO] Using JIRA_EPIC_LINK_FIELD_ID from environment: {env_id}")
                return env_id

            print("[INFO] JIRA_EPIC_LINK_FIELD_ID not set. Attempting to discover it automatically...")
            all_fields = self.client.fields()
            
            # Search for the field by its common names.
            # "Epic Link" is for company-managed projects.
            # "Parent" is sometimes used for epics in team-managed projects.
            for field in all_fields:
                if field['name'].lower() == 'epic link':
                    return field['id']
            
            # As a fallback, check for 'Parent' field that links to epics in some project types
            for field in all_fields:
                 # Check if the field is named Parent and its schema suggests it can link to Epics
                if field['name'].lower() == 'parent' and 'epic' in str(field.get('schema', {})).get('custom', '')).lower():
                    return field['id']

        except JIRAError as e:
            print(f"[ERROR] A Jira API error occurred while trying to discover fields: {e.text}")
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred during field discovery: {e}")
            
        return None # Return None if not found

    def _get_parent_info(self, issue: Any) -> Optional[Dict[str, str]]:
        """
        Extracts parent information for sub-tasks or issues linked to an epic.
        """
        parent_issue = None
        # Case 1: Issue is a sub-task (standard parent field)
        if hasattr(issue.fields, 'parent'):
            parent_issue = issue.fields.parent

        # Case 2: Issue is linked to an Epic (using discovered custom field)
        elif self.epic_link_field_id and hasattr(issue.fields, self.epic_link_field_id):
            epic_key = getattr(issue.fields, self.epic_link_field_id)
            if epic_key:
                try:
                    # Perform an API call to get full epic details. This is more robust.
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

    def fetch_jira_issues(self, jql: str, retries: int = 3) -> List[dict]:
        """
        Fetch all Jira issues matching a JQL query, with retry on rate limits.
        This version relies on the jira-python library's built-in pagination.
        """
        attempt = 0
        issues = []
        while attempt < retries:
            try:
                print(f"Fetching all issues for JQL: {jql}")
                fields_to_fetch = "*all"
                if self.epic_link_field_id:
                    fields_to_fetch += f", {self.epic_link_field_id}"
                
                # Set maxResults to None to let the library handle pagination and fetch all issues.
                issues = self.client.search_issues(
                    jql_str=jql,
                    maxResults=None,
                    fields=fields_to_fetch
                )
                print(f"Successfully fetched a total of {len(issues)} issues.")
                break  # Success, exit retry loop
            except JIRAError as e:
                if e.status_code == 429 or "rate limit" in str(e).lower():
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    print(f"Rate limit hit. Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                    attempt += 1
                else:
                    print(f"A Jira API error occurred: {e.text}")
                    raise
            except Exception as e:
                # Catch other potential exceptions that might indicate a rate limit
                if "429" in str(e):
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    print(f"Rate limit hit. Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                    attempt += 1
                else:
                    print(f"An unexpected error occurred during Jira fetch: {e}")
                    raise

        if attempt == retries:
            raise Exception("Exceeded Jira API rate limit retries")

        all_issues_data = []
        if not issues:
            return all_issues_data

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
            all_issues_data.append(issue_data)

        return all_issues_data