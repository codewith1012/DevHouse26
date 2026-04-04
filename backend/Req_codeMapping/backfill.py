import os
import json
from fastembed import TextEmbedding
from urllib import error, parse, request
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def request_json(method: str, url: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, method=method, headers=DEFAULT_HEADERS, data=data)
    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        print(f"HTTPError: {exc.read().decode('utf-8', errors='ignore')}")
        raise
    except error.URLError as exc:
        print(f"URLError: {exc.reason}")
        raise


def normalize_spaces(text: str) -> str:
    return " ".join(str(text or "").split())


def main():
    if not SUPABASE_URL or not SUPABASE_API_KEY:
        print("ERROR: Missing Supabase credentials in .env")
        return

    print("Initializing fastembed model (BAAI/bge-small-en-v1.5)...")
    # This will download the model weights to a cache folder usually on first run
    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    # Fetch rows where embedding is null
    print("Fetching Jira requirements with NULL embeddings...")
    query = "select=issue_id,title,description,issue_type,priority&embedding=is.null"
    url = f"{BASE_REST_URL}/req_code_mapping?{query}"

    rows = request_json("GET", url)
    if not rows:
        print("No requirements found that need backfilling! All clear.")
        return

    print(f"Found {len(rows)} requirements to embed.")

    for row in rows:
        issue_id = row.get("issue_id")
        title = row.get("title") or ""
        description = row.get("description") or ""
        issue_type = row.get("issue_type") or ""
        priority = row.get("priority") or ""

        # We append 'passage: ' because BAAI/bge models perform better on asymmetric tasks
        # when the indexed documents use 'passage: ' and the search queries use 'query: '
        passage_text = f"passage: {title} {description} {issue_type} {priority}"
        cleaned_text = normalize_spaces(passage_text)

        print(f"Embedding issue {issue_id}...")

        # Generates a generator, convert to list and take the first item
        embeddings = list(model.embed([cleaned_text]))
        vector = [float(v) for v in embeddings[0].tolist()]

        print(f"Saving vector ({len(vector)} dims) for {issue_id} to Supabase...")

        # Patch the row using Supabase REST API
        patch_query = f"issue_id=eq.{parse.quote(issue_id)}"
        patch_url = f"{BASE_REST_URL}/req_code_mapping?{patch_query}"

        request_json("PATCH", patch_url, payload={"embedding": vector})
        print(f"Successfully updated {issue_id}")

    print("--- BACKFILL COMPLETE ---")


if __name__ == "__main__":
    main()
