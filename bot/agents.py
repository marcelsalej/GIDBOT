"""
LangChain-like Gemini agent
"""

import google.generativeai as genai
import os
import asyncio
from bot.jira_tool_client import JiraTool
from bot.confluence_tool import ConfluenceTool

jira_tool = JiraTool()
confluence_tool = ConfluenceTool()

PROJECT_KEYS = ["ID", "WL", "MS"]  # Your Jira project keys

model = genai.GenerativeModel("gemini-2.0-flash")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

async def ask_ai_agent(prompt: str, user_id: str) -> str:
    project_key = extract_project_from_prompt(prompt)
    jira_info = ""
    print(jira_tool.list_projects())
    if project_key:
        # Optional: Your JQL query
        JQL_QUERY_ID = f'created >= \\u002d30d AND type IN (Epic, Story, Task)'
        jira_info_id = jira_info + str(jira_tool.fetch_jira_issues(JQL_QUERY_ID))
        JQL_QUERY_WL = f'created >= \\u002d30d AND type IN (Epic, Story, Task)'
        jira_info_wl = jira_info + str(jira_tool.fetch_jira_issues(JQL_QUERY_WL))
        JQL_QUERY_MS = f'created >= \\u002d30d AND type IN (Epic, Story, Task)'
        jira_info_ms = jira_info + str(jira_tool.fetch_jira_issues(JQL_QUERY_MS))
    else:
        jira_info = "No project found in your question. Please specify a valid project."


    system_context = (
    "You are a helpful assistant for a software development team. "
    "You summarize Jira ticket statuses and match Confluence docs to JIRA issues. "
    "You expose any blockers that are reported in jira "
    "When requested, you retrieve all Jira tickets that belong to the Identity team, Project name on JIRA is: ID context is {jira_info_id}"
    "identifying these tickets by their team label, component, or project field related to Identity."
    "When requested, you retrieve all Jira tickets that belong to the Wallet team, Project name on JIRA is: {jira_info_id} "
    "When requested, you retrieve all Jira tickets that belong to the Messaging team, Project name on JIRA is: MSG {jira_info_id}"
)
    tools_context = (
        f"Available tools:\n"
        f"- JiraTool: Get ticket and sprint progress\n"
        f"- ConfluenceTool: Lookup internal documentation\n"
    )

    full_prompt = f"{system_context}\n{tools_context}\n\nUser asked:\n{prompt}"

    # Run blocking Gemini call in a thread to avoid blocking event loop
    response = await asyncio.to_thread(model.generate_content, full_prompt)
    return response.text.strip()


def extract_project_from_prompt(prompt: str) -> str | None:
    prompt_lower = prompt.lower()
    for proj in PROJECT_KEYS:
        if proj.lower() in prompt_lower:
            return proj
    return None