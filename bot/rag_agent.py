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
        f"You are a senior project manager assistant AI, helping analyze Jira tickets and related project documentation.\n\n"
        f"Your goals:\n"
        f"- Summarize the status and progress of relevant Jira issues\n"
        f"- Identify blockers, risks, or dependencies\n"
        f"- Suggest next steps or actions, if any\n"
        f"- Format the response clearly for posting in Slack\n"
        f"- Add hyperlinks to any mentioned Jira tickets (base URL: {os.getenv("JIRA_BASE_URL")})"
        f"Relevant Jira tickets and Confluence content:\n{context}\n\n"
        f"User Request:\n{prompt}\n\n"
        f"Instructions:\n"
        f"- Reason like a project manager: think about timelines, blockers, dependencies, and team roles.\n"
        f"- Prioritize clarity and actionability.\n"
        f"- Structure the output with clear sections: 'Summary', 'Risks/Blockers', 'Recommended Actions', and 'Linked Tickets'.\n"
        f"- Use bullet points where helpful.\n"
        f"- Hyperlink all Jira issue keys to the base URL."
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