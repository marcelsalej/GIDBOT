"""
LangChain-like Gemini agent
"""

import os
import asyncio
import random
from typing import Optional

from bot.jira_tool_client import JiraTool
from bot.confluence_tool import ConfluenceTool # Ensure this is imported
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import initialize_agent, Tool
from langchain.memory import ConversationBufferMemory
from langchain_community.cache import InMemoryCache
from langchain.globals import set_llm_cache
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage # Import for explicit message types

# Set API key securely (should already be set in env)
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

# Initialize cache once globally
set_llm_cache(InMemoryCache())

# Init LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.4)

# Memory setup
# Initialize with a system message to set the agent's persona and instructions
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

# Directly add the system context to the memory as a SystemMessage
memory.chat_memory.add_message(SystemMessage(
    content="You are a helpful assistant for a software development team. \n"
    "You summarize Jira ticket statuses and match Confluence docs to JIRA issues. \n"
    "You expose any blockers that are reported in Jira.\n"
    "When requested, you retrieve all Jira tickets for the following:\n"
    "- Identity team: Project name = ID\n"
    "- Wallet team: Project name = WL\n"
    "- Messaging team: Project name = MS"
))

# You can also add tool context directly, or let the agent handle tool descriptions
# For clarity, let's include tools as part of the overall agent setup,
# the agent type "chat-conversational-react-description" typically handles tool descriptions well.

# Initialize tools
jira_tool = JiraTool()
confluence_tool = ConfluenceTool()

tools = [
    Tool(
        name="JiraTool",
        func=jira_tool.fetch_jira_issues,
        description="Useful for fetching Jira ticket information and progress. Provide JQL query as input.",
    ),
    Tool( # UNCOMMENTED AND INTEGRATED
        name="ConfluenceTool",
        func=confluence_tool.run, # Use the 'run' method of ConfluenceTool
        description="Useful for fetching Confluence documentation. Input should be a search query string.",
    )
]

# Agent setup
agent = initialize_agent(
    tools,
    llm,
    agent="chat-conversational-react-description",
    memory=memory,
    verbose=True,
    # agent_kwargs={"system_message": system_context} # This could also be an option for different agent types
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
    # Note: The original code filtered by issue["key"] == project_key, which seems to imply
    # filtering by a single issue key rather than project key.
    # Assuming project_key refers to the project abbreviation (ID, WL, MS),
    # we should check if issue["key"] (e.g., "ID-123") starts with the project_key.
    filtered = [issue for issue in jira_issues if issue["key"].startswith(project_key + "-")] # Adjusted filter

    count = len(filtered)

    # Define how you identify blockers
    # Example: assume "blocker" is in summary or description for simplicity if no labels field.
    # If Jira API provides labels, use issue.fields.labels
    blockers = [i for i in filtered if 'blocker' in (i.get('summary', '').lower() + i.get('description', '').lower())]

    summary = (
        f"Project {project_key} has {count} tickets currently fetched.\n" # Changed to reflect fetched, not last 30 days based on JQL
        f"{len(blockers)} potential blockers identified (based on keywords).\n"
        "Statuses:\n"
    )

    # Count statuses
    status_counts = {}
    for issue in filtered:
        status = issue.get("status", "Unknown") # Use .get for safety
        status_counts[status] = status_counts.get(status, 0) + 1

    for status, cnt in status_counts.items():
        summary += f"- {status}: {cnt}\n"

    print(f"SUMMARIZED JIRA for {project_key}: {summary}", flush=True) # Debug print for summary
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
    print(f"[DEBUG] AI agent warming up for project: {project_key}", flush=True)

    if not project_key:
        return "No project found in your question. Please specify a valid project (ID, WL, MS)."

    # Adjust JQL query based on the detected project_key for targeted fetching
    # The original JQL was 'project IN ("identity team", TRIAGE)'
    # We should refine this based on the extracted project_key for relevance.
    # For a general overview, it might still fetch broadly, but the summary will filter.
    # Let's assume the JQL needs to be dynamic for the project.
    # Mapping project keys to full project names for JQL
    project_name_map = {
        "ID": "identity team",
        "WL": "wallet team",
        "MS": "messaging team"
    }
    jql_project_name = project_name_map.get(project_key, "identity team") # Default to identity team if not found

    # Fetching issues for the specific project identified
    jql_query = f'project = "{jql_project_name}"' # Adjusted JQL to be specific
    print(f"Fetching Jira issues with JQL: {jql_query}", flush=True)

    try:
        jira_issues = jira_tool.fetch_jira_issues(jql_query)
        print(f"[DEBUG] Retrieved {len(jira_issues)} issues from Jira for {jql_project_name}", flush=True)
        jira_summary = summarize_jira_issues(jira_issues, project_key)
    except Exception as e:
        print(f"[ERROR] Jira fetch failed: {repr(e)}", flush=True)
        return f"Failed to fetch Jira issues: {e}"

    # IMPORTANT FIX: Use jira_summary, not raw jira_issues, in the prompt
    full_prompt = (
        f"User asked:\n{prompt}\n\n"
        f"Here is a summary of recent Jira tickets for {project_key}:\n{jira_summary}\n\n"
        f"Please answer the user's question using this information and your available tools."
    )

    print(f"[INFO] Prompt content for agent:\n{full_prompt}", flush=True)
    print(f"[INFO] Prompt token estimate: {len(full_prompt) / 4:.0f} tokens (rough estimate)", flush=True) # More accurate rough estimate

    try:
        response = await call_agent_with_retries(agent, full_prompt)
        return response.strip()
    except Exception as e:
        print(f"[ERROR] Agent processing failed after retries: {e}", flush=True)
        return "Service is temporarily unavailable due to rate limits. Please try again later."