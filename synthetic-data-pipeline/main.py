"""
main.py — CLI entry point for the Synthetic Data Curation Pipeline

Usage:
    # Web search (default)
    python main.py --topic "LangGraph multi-agent systems"

    # PDF input
    python main.py --topic "RAG systems" --pdf path/to/doc.pdf

    # With dataset type
    python main.py --topic "Kubernetes" --dataset-type "Q&A"
    python main.py --topic "Kubernetes" --dataset-type "Chain-of-Thought"
    python main.py --topic "Kubernetes" --dataset-type "Summarization"
"""

import argparse
import os
import sys
import time
from pipeline.graph import build_graph
from pipeline.nodes import DATASET_TYPE_CONFIGS, reset_vectorstore, extract_pdf_text
from pipeline.review import review_chunks, review_pairs


def run_pipeline(topic: str, dataset_type: str, pdf_path: str = None, pair_count: int = 10):
    print(f"\n🚀 Starting Synthetic Data Curation Pipeline")
    print(f"   Topic:        {topic}")
    print(f"   Dataset type: {dataset_type}")
    print(f"   Target pairs: {pair_count}")
    print(f"   Source:       {'PDF — ' + pdf_path if pdf_path else 'Web search'}\n")

    reset_vectorstore()

    # PDF: extract text before passing to graph
    pdf_text, pdf_filename, pdf_page_count = None, None, None
    if pdf_path:
        print(f"📄 Extracting text from: {pdf_path}")
        try:
            with open(pdf_path, "rb") as f:
                raw = f.read()
            pdf_text, pdf_page_count = extract_pdf_text(raw)
            pdf_filename = os.path.basename(pdf_path)
            print(f"  Extracted {pdf_page_count} pages, {len(pdf_text):,} chars\n")
        except (ValueError, FileNotFoundError) as e:
            print(f"❌ PDF error: {e}")
            sys.exit(1)

    graph = build_graph()
    thread_config = {"configurable": {"thread_id": f"pipeline-{int(time.time())}"}}

    initial_state = {
        "seed_topic": topic,
        "source_type": "pdf" if pdf_path else "web",
        "dataset_type": dataset_type,
        "pair_count": pair_count,
        "pdf_text": pdf_text,
        "pdf_filename": pdf_filename,
        "pdf_page_count": pdf_page_count,
        "search_results": [],
        "scraped_pages": [],
        "chunks": [],
        "chunks_pending_review": [],
        "chunks_approved": [],
        "chunks_rejected": [],
        "vectorstore_ids": [],
        "raw_pairs": [],
        "scored_pairs": [],
        "failed_pairs": [],
        "generation_attempts": 0,
        "deduped_pairs": [],
        "pairs_pending_review": [],
        "pairs_approved": [],
        "pairs_rejected": [],
        "export_path": None,
        "stats": {},
    }

    # ── Run until first interrupt (chunk review) ──────────────────────────────
    print("Running pipeline to chunk review...")
    for event in graph.stream(initial_state, config=thread_config):
        pass

    state = graph.get_state(thread_config)
    if not state.next:
        print("Pipeline ended early — no chunks produced.")
        return

    if "human_review_chunks" in state.next:
        chunks = state.values.get("chunks_pending_review", [])
        if not chunks:
            print("❌ No chunks produced.")
            return
        approved_chunks, rejected_chunks = review_chunks(chunks)
        graph.update_state(
            thread_config,
            {"chunks_approved": approved_chunks, "chunks_rejected": rejected_chunks, "chunks_pending_review": []},
            as_node="human_review_chunks",
        )

    # ── Run until second interrupt (pair review) ──────────────────────────────
    print("\nResuming pipeline to pair review...")
    for event in graph.stream(None, config=thread_config):
        pass

    state = graph.get_state(thread_config)
    if not state.next:
        print("Pipeline ended — no pairs to review (all failed scoring).")
        return

    if "human_review_pairs" in state.next:
        pairs = state.values.get("pairs_pending_review", [])
        if not pairs:
            print("❌ No pairs passed scoring.")
            return
        approved_pairs, rejected_pairs = review_pairs(pairs)
        graph.update_state(
            thread_config,
            {"pairs_approved": approved_pairs, "pairs_rejected": rejected_pairs, "pairs_pending_review": []},
            as_node="human_review_pairs",
        )

    # ── Final run — export ────────────────────────────────────────────────────
    print("\nFinalizing and exporting...")
    for event in graph.stream(None, config=thread_config):
        pass

    state = graph.get_state(thread_config)
    export_path = state.values.get("export_path")
    if export_path:
        print(f"\n✅ Dataset saved to: {export_path}")
    else:
        print("\n⚠️  No dataset exported.")


def main():
    parser = argparse.ArgumentParser(description="Synthetic Data Curation Pipeline")
    parser.add_argument("--topic", type=str, required=True, help="Seed topic / description")
    parser.add_argument("--pdf", type=str, default=None, help="Path to a PDF file (optional; overrides web search)")
    parser.add_argument(
        "--dataset-type",
        type=str,
        default="Instruction Following",
        choices=list(DATASET_TYPE_CONFIGS.keys()),
        help="Type of dataset to generate",
    )
    parser.add_argument("--api-key", type=str, default=None, help="Google API key (overrides GOOGLE_API_KEY env var)")
    parser.add_argument("--pairs", type=int, default=10, help="Target pairs per generation attempt (default: 10)")
    args = parser.parse_args()

    if not args.topic.strip():
        print("Error: --topic cannot be empty")
        sys.exit(1)

    if args.pairs < 1 or args.pairs > 50:
        print("Error: --pairs must be between 1 and 50")
        sys.exit(1)

    if args.api_key:
        os.environ["GOOGLE_API_KEY"] = args.api_key

    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set — use --api-key or export GOOGLE_API_KEY=...")
        sys.exit(1)

    run_pipeline(topic=args.topic, dataset_type=args.dataset_type, pdf_path=args.pdf, pair_count=args.pairs)


if __name__ == "__main__":
    main()
