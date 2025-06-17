"""
LangChain-like Gemini agent
"""

import os
import asyncio
import random
from typing import Optional

from bot.jira_tool_client import JiraTool
from bot.confluence_tool import ConfluenceTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import initialize_agent, Tool
from langchain.memory import ConversationBufferMemory
from langchain_community.cache import InMemoryCache
from langchain.globals import set_llm_cache

# Set API key securely (should already be set in env)
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

# Initialize cache once globally
set_llm_cache(InMemoryCache())

# Init LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.4)

# Memory setup
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

# Initialize tools
jira_tool = JiraTool()
confluence_tool = ConfluenceTool()

tools = [
    Tool(
        name="JiraTool",
        func=jira_tool.fetch_jira_issues,
        description="Useful for fetching Jira ticket information and progress",
    ),
    # Uncomment and implement if ConfluenceTool functionality is ready
    # Tool(
    #     name="ConfluenceTool",
    #     func=confluence_tool.some_function,
    #     description="Useful for fetching Confluence documentation",
    # )
]

# Agent setup
agent = initialize_agent(
    tools,
    llm,
    agent="chat-conversational-react-description",
    memory=memory,
    verbose=True,
)

# Valid project keys
PROJECT_KEYS = ["ID", "WL", "MS"]


def extract_project_from_prompt(prompt: str) -> Optional[str]:
    prompt_lower = prompt.lower()
    for proj in PROJECT_KEYS:
        if proj.lower() in prompt_lower:
            return proj
    return None

def summarize_jira_issues(jira_issues: list, project_key: str) -> str:
    filtered = [issue for issue in jira_issues if issue.get("project") == project_key]
    count = len(filtered)
    blockers = [i for i in filtered if i.get("blocker", False)]
    summary = (
        f"Project {project_key} has {count} tickets created in last 30 days.\n"
        f"{len(blockers)} blockers reported.\n"
        "Statuses:\n"
    )
    status_counts = {}
    for issue in filtered:
        status = issue.get("status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    for status, cnt in status_counts.items():
        summary += f"- {status}: {cnt}\n"

    print(f"sUMMARIZED JIRA {summary}", flush=True)
    return summary

async def ask_ai_agent(prompt: str, user_id: str) -> str:
    project_key = extract_project_from_prompt(prompt)

    if not project_key:
        return "No project found in your question. Please specify a valid project (ID, WL, MS)."

    jql_query = f'statusCategory IN ("To Do", "In Progress") ORDER BY created DESC'

    try:
        jira_issues = jira_tool.fetch_jira_issues(jql_query)
        print(f"[DEBUG] Retrieved {len(jira_issues)} issues from Jira", flush=True)
        jira_summary = summarize_jira_issues(jira_issues, project_key)
    except Exception as e:
        print(f"[ERROR] Jira fetch failed: {repr(e)}", flush=True)
        return f"Failed to fetch Jira issues: {e}"

    system_context = (
        "You are a helpful assistant for a software development team. "
        "You summarize Jira ticket statuses and match Confluence docs to JIRA issues. "
        "You expose any blockers that are reported in Jira.\n\n"
        "When requested, you retrieve all Jira tickets for the following:\n"
        "- Identity team: Project name = ID\n"
        "- Wallet team: Project name = WL\n"
        "- Messaging team: Project name is MS"
    )

    tools_context = (
        "Available tools:\n"
        "- JiraTool: Get ticket and sprint progress\n"
        "- ConfluenceTool: Lookup internal documentation\n"
    )

    full_prompt = f"{system_context}\n\n{tools_context}\n\nUser asked:\n{prompt}"

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # Add delay before calling agent to avoid Gemini burst limit
            await asyncio.sleep(1.5)

            print(f"[INFO] Attempt {attempt + 1}: Running agent chain...", flush=True)
            response = await asyncio.to_thread(agent.run, full_prompt)
            return response.strip()

        except Exception as e:
            err_msg = str(e).lower()

            if "429" in err_msg or "rate limit" in err_msg:
                wait_time = min(10, 2 ** attempt + random.uniform(0.5, 1.5))
                print(f"[WARN] Rate limit hit from Gemini API. Retrying in {wait_time:.2f}s (Attempt {attempt + 1})...", flush=True)
                await asyncio.sleep(wait_time)
            else:
                print(f"[ERROR] Agent execution failed: {repr(e)}", flush=True)
                return f"Agent processing failed: {e}"

    return "Service is temporarily unavailable due to quota limits. Please try again later."