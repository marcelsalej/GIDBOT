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
tools_context = (
    "Available tools:\n",
    "- JiraTool: Get ticket and sprint progress\n",
    "- ConfluenceTool: Lookup internal documentation\n"
)
system_context = (
    "You are a helpful assistant for a software development team. \n"
    "You summarize Jira ticket statuses and match Confluence docs to JIRA issues. \n"
    "You expose any blockers that are reported in Jira.\n"
    "When requested, you retrieve all Jira tickets for the following:\n"
    "- Identity team: Project name = ID\n"
    "- Wallet team: Project name = WL\n"
    "- Messaging team: Project name = MS"
)
memory.chat_memory.add_ai_message(system_context)
memory.chat_memory.add_ai_message(tools_context)

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
    # Filter issues that belong to the given project
    filtered = [issue for issue in jira_issues if issue["key"] == project_key]
    count = len(filtered)

    # Define how you identify blockers
    # Example: assume "blocker" is a label
    blockers = [i for i in filtered if 'blocker' in getattr(i, 'labels', [])]

    summary = (
        f"Project {project_key} has {count} tickets created in last 30 days.\n"
        f"{len(blockers)} blockers reported.\n"
        "Statuses:\n"
    )

    # Count statuses
    status_counts = {}
    for issue in filtered:
        status = issue.status.name
        status_counts[status] = status_counts.get(status, 0) + 1

    for status, cnt in status_counts.items():
        summary += f"- {status}: {cnt}\n"

    print(f"sUMMARIZED JIRA {filtered}", flush=True)
    return summary

async def call_agent_with_retries(agent, prompt, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            print(f"[INFO] Attempt {attempt + 1}: Calling Gemini agent...", flush=True)
            return await asyncio.to_thread(agent.run, prompt)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "resourceexhausted" in err_str or "rate limit" in err_str:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"[WARN] Rate limit hit. Waiting {wait_time:.2f}s before retry (Attempt {attempt + 1})", flush=True)
                await asyncio.sleep(wait_time)
            else:
                print(f"[ERROR] Agent call failed: {e}", flush=True)
                raise e
    raise Exception("Exceeded maximum retry attempts due to rate limiting.")

async def ask_ai_agent(prompt: str, user_id: str) -> str:
    project_key = extract_project_from_prompt(prompt)
    print(f"[DEBUG] AI agent warming up {project_key}", flush=True)

    if not project_key:
        return "No project found in your question. Please specify a valid project (ID, WL, MS)."

    jql_query = f'project IN ("identity team", TRIAGE)'
    print(f"Fetching jira issues", flush=True)

    try:
        jira_issues = jira_tool.fetch_jira_issues(jql_query)
        print(f"[DEBUG] Retrieved {len(jira_issues)} issues from Jira", flush=True)
        jira_summary = summarize_jira_issues(jira_issues, project_key)
    except Exception as e:
        print(f"[ERROR] Jira fetch failed: {repr(e)}", flush=True)
        return f"Failed to fetch Jira issues: {e}"

    full_prompt = (
        f"User asked:\n{prompt}\n\n",
        f"Here is a summary of recent Jira tickets:\n{jira_issues}"
    )

    print(f"[INFO] Prompt token estimate: {len(full_prompt) * 1.2:.0f} tokens", flush=True)

    try:
        response = await call_agent_with_retries(agent, full_prompt)
        return response.strip()
    except Exception as e:
        print(f"[ERROR] Agent processing failed after retries: {e}", flush=True)
        return "Service is temporarily unavailable due to rate limits. Please try again later."