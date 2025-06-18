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

# --- NEW FUNCTION TO INDEX GITHUB PRS ---
def index_github_prs(github_prs):
    print(f"[DEBUG] Start Indexing {len(github_prs)} GitHub PRs...", flush=True)
    documents = []
    for pr in github_prs:
        body = pr['body'][:500] if pr['body'] else ""
        text = (
            f"GitHub PR #{pr['number']}: {pr['title']}\n"
            f"Status: {pr['state']}\n"
            f"Author: {pr['user']}\n"
            f"Last Updated: {pr['updated_at']}\n"
            f"Body: {body}..."
        )
        metadata = {
            "number": pr['number'],
            "title": pr['title'],
            "state": pr['state'],
            "user": pr['user'],
            "url": pr['url'],
            "source": "github" # Add a source metadata field
        }
        documents.append(Document(page_content=text, metadata=metadata))
    
    if documents:
        chroma.add_documents(documents)
        print(f"[DEBUG] Added {len(documents)} GitHub documents to ChromaDB.", flush=True)
    else:
        print("[DEBUG] No GitHub documents to add to ChromaDB.", flush=True)

def index_confluence_pages(confluence_pages):
    print(f"[DEBUG] Start Indexing {len(confluence_pages)} Confluence pages...", flush=True)
    documents = []
    for page in confluence_pages:
        # Truncate long page bodies to keep context manageable for the LLM
        body = page['body'][:2000] if page['body'] else ""

        text = (
            f"Confluence Document: {page['title']}\n\n"
            f"{body}..."
        )

        metadata = {
            "id": page['id'],
            "title": page['title'],
            "url": page['url'],
            "source": "confluence" # Critical for identifying the data source
        }
        documents.append(Document(page_content=text, metadata=metadata))
    
    if documents:
        chroma.add_documents(documents)
        print(f"[DEBUG] Added {len(documents)} Confluence documents to ChromaDB.", flush=True)
    else:
        print("[DEBUG] No Confluence documents to add to ChromaDB.", flush=True)

def query_relevant_issues(query_text, k=5):
    print(f"[DEBUG] Querying relevant issues from ChromaDB for: {query_text}", flush=True)
    return chroma.similarity_search(query_text, k=k)