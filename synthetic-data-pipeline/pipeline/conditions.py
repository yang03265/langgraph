"""
Conditional edge routing functions for the pipeline graph
"""

MAX_GENERATION_ATTEMPTS = 3
MIN_PAIRS_TO_CONTINUE = 3


def route_source(state: dict) -> str:
    """Branch from START to pdf_ingest or search based on source_type."""
    if state.get("source_type") == "pdf":
        print("\n📄 Source: PDF — skipping web search")
        return "pdf"
    print("\n🌐 Source: Web search")
    return "web"


def route_after_chunk_review(state: dict) -> str:
    """Proceed to store if any chunks approved, else end."""
    if not state.get("chunks_approved"):
        print("\n⚠️  No chunks approved. Ending pipeline.")
        return "end"
    return "store"


def route_after_scoring(state: dict) -> str:
    """Retry generation if too few pairs passed, else continue to dedup.

    generation_attempts is already incremented by generate_node before
    score_node runs, so this compares against the current count.
    """
    scored = state.get("scored_pairs", [])
    attempts = state.get("generation_attempts", 0)

    if len(scored) < MIN_PAIRS_TO_CONTINUE and attempts < MAX_GENERATION_ATTEMPTS:
        print(f"\n🔁 Only {len(scored)} pairs passed. Retrying ({attempts}/{MAX_GENERATION_ATTEMPTS})...")
        return "retry"
    return "continue"


def route_after_pair_review(state: dict) -> str:
    """Export if any pairs approved, else end."""
    if not state.get("pairs_approved"):
        print("\n⚠️  No pairs approved. Ending pipeline.")
        return "end"
    return "export"
