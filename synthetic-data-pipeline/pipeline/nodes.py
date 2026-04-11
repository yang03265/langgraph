"""
Pipeline nodes — each node receives and returns PipelineState
"""

import io
import os
import re
import uuid
import json
import threading
from typing import List, Optional
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.embeddings import Embeddings
from langchain_core.messages import SystemMessage, HumanMessage


# ── LLM client ────────────────────────────────────────────────────────────────

def get_llm():
    """Always reads API key at call time so re-runs with new keys work.

    - thinking_budget=0: disable Gemini 2.5's reasoning tokens (not needed for
      structured JSON generation, and they eat into max_output_tokens).
    - response_mime_type="application/json": force the model to emit valid JSON
      so we don't have to rely on prompt-engineered fences.
    """
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.7,
        max_output_tokens=8192,
        thinking_budget=0,
        response_mime_type="application/json",
    )


# ── Vector store (thread-safe singleton, local sentence-transformers) ────────

class LocalSentenceEmbeddings(Embeddings):
    """LangChain Embeddings wrapper around the shared SentenceTransformer singleton.
    Runs locally — no API quota, no rate limits."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = get_sentence_model()
        return model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> List[float]:
        model = get_sentence_model()
        return model.encode(text, normalize_embeddings=True).tolist()


_vectorstore = None
_vectorstore_lock = threading.Lock()

def get_vectorstore():
    global _vectorstore
    with _vectorstore_lock:
        if _vectorstore is None:
            _vectorstore = Chroma(
                collection_name="synthetic_data_pipeline",
                embedding_function=LocalSentenceEmbeddings(),
                persist_directory="./data/chroma",
            )
    return _vectorstore


def reset_vectorstore():
    """Delete and recreate the Chroma collection before each pipeline run."""
    global _vectorstore
    with _vectorstore_lock:
        if _vectorstore is not None:
            try:
                _vectorstore.delete_collection()
            except Exception:
                pass
        _vectorstore = None


# ── Sentence transformer for deduplication (thread-safe singleton) ────────────
# Local model (80MB) — avoids extra API calls for simple cosine similarity.

_sentence_model = None
_sentence_model_lock = threading.Lock()

def get_sentence_model():
    global _sentence_model
    with _sentence_model_lock:
        if _sentence_model is None:
            _sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _sentence_model


# ── JSON fence stripper ───────────────────────────────────────────────────────

def strip_json_fences(text: str) -> str:
    """Robustly strip ```json...``` or ```...``` fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Dataset type configs ──────────────────────────────────────────────────────

DATASET_TYPE_CONFIGS = {
    "Instruction Following": {
        "description": "General instruction → output pairs for fine-tuning",
        "generation_description": "instruction-output pairs for general fine-tuning",
        "schema": '[{"instruction": "...", "input": "", "output": "..."}]',
        "guidance": "Cover different difficulty levels (basic, intermediate, advanced) and question types (factual, explanatory, comparative, applied).",
        "k": 8,
        "include_input_in_scoring": False,
    },
    "Q&A": {
        "description": "Question → answer pairs grounded in source content",
        "generation_description": "question-answer pairs grounded in the source content",
        "schema": '[{"instruction": "Question: ...", "input": "", "output": "Answer: ..."}]',
        "guidance": "Generate clear, specific questions with concise, accurate answers directly supported by the source content.",
        "k": 8,
        "include_input_in_scoring": False,
    },
    "Chain-of-Thought": {
        "description": "Step-by-step reasoning before the final answer",
        "generation_description": "instruction-output pairs where the output includes explicit step-by-step reasoning before the final answer",
        "schema": '[{"instruction": "...", "input": "", "output": "Let me think step by step...\\n\\nStep 1: ...\\nStep 2: ...\\n\\nTherefore: ..."}]',
        "guidance": "Each output must show explicit reasoning steps before reaching a conclusion. Prioritize analytical and applied questions that benefit from step-by-step thinking.",
        "k": 10,
        "include_input_in_scoring": False,
    },
    "Summarization": {
        "description": "Passage → concise summary pairs",
        "generation_description": "summarization pairs where the instruction asks to summarize a passage and the output is a concise summary",
        "schema": '[{"instruction": "Summarize the following passage:", "input": "<passage from source>", "output": "<concise summary>"}]',
        "guidance": "The input field must contain a real passage from the source content. The output must be a concise, accurate summary of that passage.",
        "k": 5,
        "include_input_in_scoring": True,
    },
}


# ── PDF extraction helper ─────────────────────────────────────────────────────
# Called in app.py / main.py BEFORE the graph starts.
# Avoids storing raw bytes in LangGraph state (serialization issues + memory bloat).

def extract_pdf_text(pdf_bytes: bytes) -> tuple:
    """
    Extract text from PDF bytes. Returns (full_text: str, page_count: int).
    Raises ValueError if extraction fails or content is too short.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = len(reader.pages)
    pages_text = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages_text.append(text)

    full_text = "\n\n".join(pages_text)

    if len(full_text) < 200:
        raise ValueError("PDF content too short or unreadable — try a text-based PDF")

    return full_text, page_count


# ── Node 0: PDF Ingest ────────────────────────────────────────────────────────
# Receives pre-extracted text from state["pdf_text"] — not raw bytes.

def pdf_ingest_node(state: dict) -> dict:
    pdf_text = state["pdf_text"]
    filename = state.get("pdf_filename", "uploaded.pdf")
    pdf_page_count = state.get("pdf_page_count", 1)
    print(f"\n📄 Chunking PDF: {filename} ({pdf_page_count} pages, {len(pdf_text):,} chars)")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " "],
    )
    chunks = [
        {
            "id": str(uuid.uuid4()),
            "url": f"pdf://{filename}",
            "title": filename,
            "text": text,
            "chunk_index": i,
        }
        for i, text in enumerate(splitter.split_text(pdf_text))
    ]

    print(f"  Generated {len(chunks)} chunks")

    # Synthetic scraped_pages entry for export stats.
    # Store empty content to avoid duplicating the full PDF text in state.
    scraped_pages = [{
        "url": f"pdf://{filename}",
        "title": filename,
        "content": "",           # intentionally empty — full text already in pdf_text
        "status": "ok",
        "page_count": pdf_page_count,
    }]

    return {
        "search_results": [],
        "scraped_pages": scraped_pages,
        "chunks": chunks,
        "chunks_pending_review": chunks,
        "chunks_approved": [],
        "chunks_rejected": [],
    }


# ── Node 1: Search ────────────────────────────────────────────────────────────

_DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_DDG_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _ddg_unwrap(href: str) -> str:
    """DuckDuckGo wraps result links as /l/?uddg=<encoded-url>. Unwrap them."""
    if "duckduckgo.com/l/" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _ddg_search(query: str, max_results: int = 10) -> list:
    """Search DuckDuckGo via the HTML endpoint using requests (stable TLS)."""
    resp = requests.post(
        _DDG_HTML_ENDPOINT,
        data={"q": query, "b": "", "kl": "wt-wt"},
        headers={"User-Agent": _DDG_UA},
        timeout=15,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for node in soup.select("div.result")[: max_results * 2]:
        title_el = node.select_one("a.result__a")
        snippet_el = node.select_one(".result__snippet")
        if not title_el:
            continue
        url = _ddg_unwrap(title_el.get("href", ""))
        if not url.startswith("http"):
            continue
        # Skip DuckDuckGo ad redirects (y.js?ad_provider=...)
        if "duckduckgo.com/y.js" in url or "ad_provider=" in url:
            continue
        results.append({
            "url": url,
            "title": title_el.get_text(strip=True),
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
        if len(results) >= max_results:
            break
    return results


def search_node(state: dict) -> dict:
    print(f"\n🔍 Searching DuckDuckGo for: '{state['seed_topic']}'")
    results = _ddg_search(state["seed_topic"], max_results=10)
    for r in results:
        print(f"  → {r['title'][:60]}")
    print(f"  Found {len(results)} results")
    return {"search_results": results}


# ── Node 2: Scrape (parallel) ─────────────────────────────────────────────────

def _scrape_one(result: dict) -> dict:
    url = result["url"]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SyntheticDataBot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = "\n".join(l.strip() for l in soup.get_text(separator="\n", strip=True).splitlines() if l.strip())

        if len(text) < 200:
            raise ValueError("Content too short")

        print(f"  ✓ {result['title'][:50]} ({len(text)} chars)")
        return {"url": url, "title": result["title"], "content": text, "status": "ok"}

    except Exception as e:
        print(f"  ✗ {result['title'][:50]} — {e}")
        return {"url": url, "title": result["title"], "content": "", "status": f"failed: {e}"}


def scrape_node(state: dict) -> dict:
    print(f"\n🌐 Scraping {len(state['search_results'])} pages in parallel...")
    results = state["search_results"]
    scraped = [None] * len(results)

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_idx = {executor.submit(_scrape_one, r): i for i, r in enumerate(results)}
        for future in as_completed(future_to_idx):
            scraped[future_to_idx[future]] = future.result()

    successful = [p for p in scraped if p["status"] == "ok"]
    print(f"  Scraped {len(successful)}/{len(scraped)} pages successfully")
    return {"scraped_pages": scraped}


# ── Node 3: Chunk ─────────────────────────────────────────────────────────────

def chunk_node(state: dict) -> dict:
    print(f"\n✂️  Chunking scraped content...")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " "],
    )

    chunks = []
    for page in state["scraped_pages"]:
        if page["status"] != "ok":
            continue
        for i, text in enumerate(splitter.split_text(page["content"])):
            chunks.append({
                "id": str(uuid.uuid4()),
                "url": page["url"],
                "title": page["title"],
                "text": text,
                "chunk_index": i,
            })

    successful_pages = len([p for p in state["scraped_pages"] if p["status"] == "ok"])
    print(f"  Generated {len(chunks)} chunks from {successful_pages} pages")
    return {
        "chunks": chunks,
        "chunks_pending_review": chunks,
        "chunks_approved": [],
        "chunks_rejected": [],
    }


# ── Node 4: Human Review — Chunks ─────────────────────────────────────────────
# Interrupted BEFORE execution. Human decisions injected via update_state().

def human_review_chunks_node(state: dict) -> dict:
    approved = state.get("chunks_approved", [])
    rejected = state.get("chunks_rejected", [])
    print(f"\n✅ Chunk review complete: {len(approved)} approved, {len(rejected)} rejected")
    return {}


# ── Node 5: Store Chunks ──────────────────────────────────────────────────────

def store_chunks_node(state: dict) -> dict:
    approved = state["chunks_approved"]
    print(f"\n📦 Storing {len(approved)} approved chunks in vector store...")

    vs = get_vectorstore()
    vs.add_texts(
        texts=[c["text"] for c in approved],
        metadatas=[{"id": c["id"], "url": c["url"], "title": c["title"]} for c in approved],
        ids=[c["id"] for c in approved],
    )

    print(f"  Stored {len(approved)} chunks")
    return {"vectorstore_ids": [c["id"] for c in approved]}


# ── Node 6: Generate ──────────────────────────────────────────────────────────

def generate_node(state: dict) -> dict:
    attempts = state.get("generation_attempts", 0) + 1
    dataset_type = state.get("dataset_type", "Instruction Following")
    cfg = DATASET_TYPE_CONFIGS.get(dataset_type, DATASET_TYPE_CONFIGS["Instruction Following"])
    pair_count = max(1, int(state.get("pair_count") or 10))
    print(f"\n🤖 Generating {pair_count} {dataset_type} pairs (attempt {attempts})...")

    vs = get_vectorstore()
    llm = get_llm()

    # Scale retrieval so larger requests get proportionally more context.
    # Capped at 20 to keep the prompt size bounded.
    k = max(cfg["k"], min(pair_count, 20))
    docs = vs.similarity_search(state["seed_topic"], k=k)

    # Guard: if vector store returned nothing, abort generation rather than
    # sending an ungrounded prompt to the LLM
    if not docs:
        print("  ⚠️  No documents retrieved from vector store — skipping generation")
        return {
            "raw_pairs": [],
            "scored_pairs": [],
            "failed_pairs": [],
            "generation_attempts": attempts,
        }

    context = "\n\n---\n\n".join([d.page_content for d in docs])

    system_prompt = f"""You are an expert dataset curator. Given the provided context, generate {pair_count} diverse, high-quality {cfg['generation_description']} for fine-tuning a language model.

Each pair must:
- Be directly grounded in the provided context
- {cfg['guidance']}
- Have complete, accurate outputs

If the context does not contain enough distinct material for {pair_count} grounded pairs, return fewer pairs rather than fabricating content.

Return ONLY a valid JSON array with this exact format:
{cfg['schema']}

No preamble, no explanation, just the JSON array."""

    user_prompt = f"""Topic: {state['seed_topic']}

Context:
{context}

Generate up to {pair_count} {cfg['generation_description']} based on the above context."""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])

    pairs = []
    gen_error = None
    raw_content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = json.loads(strip_json_fences(raw_content))
        # response_mime_type=application/json can return a dict wrapping the
        # array (e.g. {"pairs": [...]}) — unwrap the first list value if so.
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
        if not isinstance(parsed, list):
            raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
        for p in parsed:
            p["id"] = str(uuid.uuid4())
            p["source_chunks"] = [d.metadata.get("id") for d in docs]
            p["generated_at"] = datetime.utcnow().isoformat()
        pairs = parsed
    except Exception as e:
        gen_error = f"{type(e).__name__}: {e} | raw[:200]={raw_content[:200]!r}"
        print(f"  ⚠️  Failed to parse LLM response: {gen_error}")

    print(f"  Generated {len(pairs)} pairs")
    return {
        "raw_pairs": pairs,
        "scored_pairs": [],
        "failed_pairs": [],
        "generation_attempts": attempts,
        "last_error": gen_error,
    }


# ── Node 7: Score (batched) ───────────────────────────────────────────────────

def score_node(state: dict) -> dict:
    pairs = state["raw_pairs"]
    dataset_type = state.get("dataset_type", "Instruction Following")
    cfg = DATASET_TYPE_CONFIGS.get(dataset_type, DATASET_TYPE_CONFIGS["Instruction Following"])
    include_input = cfg.get("include_input_in_scoring", False)

    # Guard: short-circuit immediately if there's nothing to score
    if not pairs:
        print("\n🎯 No pairs to score — skipping")
        return {"scored_pairs": [], "failed_pairs": []}

    print(f"\n🎯 Scoring {len(pairs)} pairs (batched)...")

    llm = get_llm()
    scored = []
    failed = []

    def pair_text(i, p):
        lines = [f"Pair {i+1}:", f"Instruction: {p['instruction']}"]
        # Include input for Summarization so judge can verify output matches passage
        if include_input and p.get("input"):
            lines.append(f"Input: {p['input']}")
        lines.append(f"Output: {p['output']}")
        return "\n".join(lines)

    pairs_text = "\n\n".join([pair_text(i, p) for i, p in enumerate(pairs)])

    system_prompt = f"""You are a strict dataset quality judge. Score each instruction-output pair on three dimensions:
- accuracy (0-10): Is the output factually correct and grounded?
- clarity (0-10): Is the instruction clear and unambiguous?
- completeness (0-10): Does the output fully address the instruction?

Return ONLY a valid JSON array with exactly {len(pairs)} objects, one per pair, in the same order:
[
  {{"accuracy": <int>, "clarity": <int>, "completeness": <int>, "feedback": "<one sentence>"}},
  ...
]

No preamble, no explanation, just the JSON array."""

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Score these {len(pairs)} pairs:\n\n{pairs_text}"),
        ])
        all_scores = json.loads(strip_json_fences(response.content))

        for i, (pair, scores) in enumerate(zip(pairs, all_scores)):
            try:
                avg = (scores["accuracy"] + scores["clarity"] + scores["completeness"]) / 3
                pair = dict(pair)
                pair["scores"] = scores
                pair["avg_score"] = avg
                if avg >= 6.0:
                    scored.append(pair)
                    print(f"  ✓ Pair {i+1} {avg:.1f} — {pair['instruction'][:50]}")
                else:
                    failed.append(pair)
                    print(f"  ✗ Pair {i+1} {avg:.1f} — {pair['instruction'][:50]} ({scores.get('feedback','')})")
            except Exception as e:
                print(f"  ⚠️  Score parse error pair {i+1}: {e}")
                failed.append(pair)

    except Exception as e:
        print(f"  ⚠️  Batch scoring failed: {e}")
        failed = list(pairs)

    # Fallback: on the final attempt, if fewer than MIN_PAIRS_TO_CONTINUE pairs
    # passed the threshold, promote the highest-scoring failed pairs so the user
    # can still review them manually instead of losing the entire run.
    from pipeline.conditions import MAX_GENERATION_ATTEMPTS, MIN_PAIRS_TO_CONTINUE
    attempts = state.get("generation_attempts", 0)
    if len(scored) < MIN_PAIRS_TO_CONTINUE and attempts >= MAX_GENERATION_ATTEMPTS and failed:
        failed_sorted = sorted(failed, key=lambda p: p.get("avg_score", 0), reverse=True)
        n = min(len(failed_sorted), max(MIN_PAIRS_TO_CONTINUE, 10))
        promoted = failed_sorted[:n]
        for p in promoted:
            p["below_threshold"] = True
        scored.extend(promoted)
        failed = failed_sorted[n:]
        print(f"  ⚠️  No pairs met 6.0 threshold after {attempts} attempts — promoting top {len(promoted)} for manual review")

    print(f"  Passed: {len(scored)}, Failed: {len(failed)}")
    return {"scored_pairs": scored, "failed_pairs": failed}


# ── Node 8: Deduplicate ───────────────────────────────────────────────────────

def deduplicate_node(state: dict) -> dict:
    pairs = state["scored_pairs"]
    print(f"\n🔄 Deduplicating {len(pairs)} pairs...")

    if not pairs:
        return {"deduped_pairs": [], "pairs_pending_review": [], "pairs_approved": [], "pairs_rejected": []}

    model = get_sentence_model()
    embeddings = model.encode([p["instruction"] for p in pairs], normalize_embeddings=True)

    keep = []
    removed = 0
    for i in range(len(pairs)):
        if any(float(np.dot(embeddings[i], embeddings[j])) > 0.92 for j in keep):
            removed += 1
        else:
            keep.append(i)

    deduped = [pairs[i] for i in keep]
    print(f"  Removed {removed} duplicates, keeping {len(deduped)} pairs")
    return {
        "deduped_pairs": deduped,
        "pairs_pending_review": deduped,
        "pairs_approved": [],
        "pairs_rejected": [],
    }


# ── Node 9: Human Review — Pairs ──────────────────────────────────────────────
# Interrupted BEFORE execution. Same pattern as chunk review.

def human_review_pairs_node(state: dict) -> dict:
    approved = state.get("pairs_approved", [])
    rejected = state.get("pairs_rejected", [])
    print(f"\n✅ Pair review complete: {len(approved)} approved, {len(rejected)} rejected")
    return {}


# ── Node 10: Export ───────────────────────────────────────────────────────────

def export_node(state: dict) -> dict:
    pairs = state["pairs_approved"]
    print(f"\n💾 Exporting {len(pairs)} approved pairs...")

    os.makedirs("data/output", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    topic_slug = state["seed_topic"].replace(" ", "_")[:30]
    path = f"data/output/{topic_slug}_{timestamp}.jsonl"

    with open(path, "w") as f:
        for pair in pairs:
            f.write(json.dumps({
                "instruction": pair["instruction"],
                "input": pair.get("input", ""),
                "output": pair["output"],
            }) + "\n")

    # For PDF runs, report actual PDF page count
    scraped = state.get("scraped_pages", [])
    if scraped and scraped[0].get("url", "").startswith("pdf://"):
        pages_stat = scraped[0].get("page_count", 1)
    else:
        pages_stat = len([p for p in scraped if p["status"] == "ok"])

    stats = {
        "seed_topic": state["seed_topic"],
        "source_type": state.get("source_type", "web"),
        "dataset_type": state.get("dataset_type", "Instruction Following"),
        "pages_scraped": pages_stat,
        "chunks_approved": len(state["chunks_approved"]),
        "pairs_generated": len(state["raw_pairs"]),
        "pairs_passed_scoring": len(state["scored_pairs"]),
        "pairs_after_dedup": len(state["deduped_pairs"]),
        "pairs_exported": len(pairs),
        "export_path": path,
        "exported_at": datetime.utcnow().isoformat(),
    }

    print(f"\n{'='*50}")
    print(f"  Pipeline complete! {len(pairs)} pairs → {path}")
    print(f"{'='*50}\n")

    return {"export_path": path, "stats": stats}
