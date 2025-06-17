# bot/vector_store.py

from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.schema import Document
import os

# Ensure API key is set
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

# Set up embeddings
embedding = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

# Chroma vector store
chroma = Chroma(
    collection_name="jira_issues",
    embedding_function=embedding,
    persist_directory=".chroma"  # persists across runs
)


def index_jira_issues(jira_issues):
    print(f"[DEBUG] Start Indexing {len(jira_issues)} Jira issues with all fields...", flush=True)
    documents = []
    for issue in jira_issues:
        key = issue["key"]
        summary = issue["summary"]
        status = issue["status"]
        assignee = issue["assignee"]
        updated = issue["updated"]
        description = issue["description"]
        url = issue["url"]
        desc = description[:500] if description else ""
    
        
        # Construct a more comprehensive text for the document to be indexed
        text = (
            f"Jira Ticket: {key}\n"
            f"Summary: {summary}\n"
            f"Status: {status}\n"
            f"Updated: {updated}\n"
            f"Assignee: {assignee}\n"
            f"Description: {desc}..." # Truncate long descriptions
        )
        
        metadata = {
            "key": key,
            "summary": summary,
            "status": status,
            "updated": updated,
            "assignee": assignee,
            "url": url
        }
        documents.append(Document(page_content=text, metadata=metadata))

    if documents:
        chroma.add_documents(documents)
        print(f"[DEBUG] Added {len(documents)} documents to ChromaDB.", flush=True)
    else:
        print("[DEBUG] No documents to add to ChromaDB.", flush=True)


def query_relevant_issues(query_text, k=5):
    print(f"[DEBUG] Querying relevant issues from ChromaDB for: {query_text}", flush=True)
    return chroma.similarity_search(query_text, k=k)