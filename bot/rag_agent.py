# bot/rag_agent.py

import os
import asyncio
from langchain_google_genai import ChatGoogleGenerativeAI
# Removed: from bot.jira_tool_client import JiraTool (no longer fetches here)
from bot.vector_store import query_relevant_issues # Removed index_jira_issues (called from main.py)

# Set up the LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.4)
# Removed: jira_tool = JiraTool() (instance managed in main.py)

async def ask_ai_rag(prompt: str, user_id: str) -> str:
    # Removed: jql_query and direct Jira fetching/indexing
    # Jira issues are assumed to be preloaded and indexed on application startup.

    try:
        print(f"[DEBUG] Searching for relevant issues for: {prompt} from preloaded index", flush=True)
        # This will now query the ChromaDB that was populated on startup
        docs = query_relevant_issues(prompt, k=8) #

        if not docs:
            return "No relevant Jira tickets found for your question."

    except Exception as e:
        return f"[ERROR] Vector search failed: {e}"

    context = "\n".join([doc.page_content for doc in docs])
    final_prompt = (
        f"You are a senior AI assistant acting as a virtual project manager for our company. "
        f"You analyze Jira tickets, Confluence pages, and project metadata to assist the team.\n\n"
        f"Goals:\n"
        f"- Summarize the current state of the project and its Jira issues\n"
        f"- Identify risks, blockers, delays, or unresolved dependencies\n"
        f"- Propose clear, actionable next steps and responsible parties\n"
        f"- Flag any misalignments with deadlines or team workloads\n"
        f"- Include hyperlinks to Jira issues (base URL: {os.getenv('JIRA_BASE_URL')})\n\n"
        f"User Request:\n{prompt}\n\n"
        f"Relevant Jira tickets and Confluence content:\n{context}\n\n"
        f"Instructions:\n"
        f"- Only analyze issues relevant to the project requested by the user (based on project key, epic, or label).\n"
        f"- Think like a project manager: consider timelines, workload balance, issue status, and team communication.\n"
        f"- Flag anything overdue, unassigned, unresolved for a long time, or stuck in progress.\n"
        f"- Group related issues under components or epics when summarizing.\n"
        f"- Highlight any cross-project or external dependencies.\n"
        f"- Include 'Summary', 'Risks/Blockers', 'Recommended Actions', and 'Linked Tickets' sections.\n"
        f"- Use bullet points and bold important phrases (e.g., deadlines, blockers).\n"
        f"- Hyperlink Jira keys using base URL.\n"
    )

    try:
        print(f"[DEBUG] Calling Gemini LLM with compressed prompt {final_prompt} ", flush=True)
        ai_response_chunks = []
        async for chunk in llm.astream(final_prompt):
            ai_response_chunks.append(chunk.content)
        ai_response = "".join(ai_response_chunks)

        return ai_response

    except Exception as e:
        return f"[ERROR] LLM processing failed: {e}"