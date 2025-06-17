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
        f"You are an expert assistant helping with Jira analysis.\n\n"
        f"Relevant Jira tickets:\n{context}\n\n"
        f"User asked:\n{prompt}\n\n"
        f"Provide your analysis based on the tickets above."
        f"Edit output for post on Slack"
        f"Add hyperlink to JIRA whenewer possible. Base url is {os.getenv("JIRA_BASE_URL")}"
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