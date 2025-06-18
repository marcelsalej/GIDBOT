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
    """
    Indexes Jira issues with a two-pass approach to create parent-child links.
    """
    print(f"[DEBUG] Starting two-pass indexing for {len(jira_issues)} Jira issues...", flush=True)
    
    # --- PASS 1: Process all issues and store them in a dictionary ---
    processed_issues = {}
    for issue_data in jira_issues:
        key = issue_data["key"]
        processed_issues[key] = {
            "summary": issue_data["summary"],
            "status": issue_data["status"],
            "assignee": issue_data["assignee"],
            "updated": issue_data["updated"],
            "description": issue_data["description"][:500] if issue_data["description"] else "",
            "url": issue_data["url"],
            "parent": issue_data.get("parent"),
            "children": []  # Initialize an empty list for child tickets
        }

    # --- PASS 2: Build the relationships ---
    for key, issue in processed_issues.items():
        parent_info = issue.get("parent")
        if parent_info and parent_info["key"] in processed_issues:
            parent_key = parent_info["key"]
            # Add this issue as a child to its parent
            processed_issues[parent_key]["children"].append({
                "key": key,
                "summary": issue["summary"],
                "status": issue["status"]
            })

    # --- FINAL PASS: Create LangChain Documents from processed issues ---
    documents = []
    for key, issue in processed_issues.items():
        # --- Create Parent Text ---
        parent_text = ""
        if issue["parent"]:
            p_info = issue["parent"]
            parent_text = f"This ticket's Parent is {p_info['key']} ({p_info.get('summary', '')}).\n"

        # --- Create Children Text ---
        children_text = ""
        if issue["children"]:
            # This issue is a parent. List its children.
            children_list = "\n".join([f"- {c['key']}: {c['summary']} ({c['status']})" for c in issue["children"]])
            children_text = f"This ticket is a Parent. It contains the following child tickets:\n{children_list}\n"
            
        # --- Construct the final document content ---
        text = (
            f"Jira Ticket: {key}\n"
            f"Summary: {issue['summary']}\n"
            f"Status: {issue['status']}\n"
            f"Assignee: {issue['assignee']}\n"
            f"Description: {issue['description']}\n\n"
            f"{parent_text}"   # e.g., "This ticket's Parent is PROJ-550."
            f"{children_text}" # e.g., "This ticket is a Parent and contains child ticket PROJ-556."
        )

        metadata = {
            "key": key,
            "summary": issue["summary"],
            "status": issue["status"],
            "url": issue["url"],
            "parent_key": issue["parent"]["key"] if issue["parent"] else None,
            "has_children": len(issue["children"]) > 0,
            "source": "jira"
        }
        documents.append(Document(page_content=text, metadata=metadata))

    if documents:
        # Clear old entries before adding new ones to prevent duplicates if run multiple times
        try:
            # Note: This is a simple way to clear. For production, more robust ID management is better.
            collection_count = chroma.get().get('ids', [])
            if collection_count:
                print(f"[DEBUG] Clearing {len(collection_count)} old documents from collection.")
                chroma.delete(ids=collection_count)
        except Exception as e:
            print(f"[WARN] Could not clear Chroma collection. This might lead to duplicate data. Error: {e}")

        chroma.add_documents(documents)
        print(f"[DEBUG] Finished indexing. Added {len(documents)} interlinked documents to ChromaDB.", flush=True)
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