"""
Synthetic Data Curation Pipeline — LangGraph graph definition
"""

from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from pipeline.nodes import (
    pdf_ingest_node,
    search_node,
    scrape_node,
    chunk_node,
    human_review_chunks_node,
    store_chunks_node,
    generate_node,
    score_node,
    deduplicate_node,
    human_review_pairs_node,
    export_node,
)
from pipeline.conditions import (
    route_source,
    route_after_chunk_review,
    route_after_scoring,
    route_after_pair_review,
)


class PipelineState(TypedDict):
    # Input
    seed_topic: str
    source_type: str            # "web" | "pdf"
    dataset_type: str           # "Instruction Following" | "Q&A" | "Chain-of-Thought" | "Summarization"
    pair_count: int             # target number of pairs per generation attempt

    # PDF source — pre-extracted text passed in (not raw bytes)
    pdf_text: Optional[str]
    pdf_filename: Optional[str]
    pdf_page_count: Optional[int]

    # Web source
    search_results: List[dict]
    scraped_pages: List[dict]

    # Chunking
    chunks: List[dict]

    # Human review — chunks
    chunks_pending_review: List[dict]
    chunks_approved: List[dict]
    chunks_rejected: List[dict]

    # Vector store
    vectorstore_ids: List[str]

    # Generation
    raw_pairs: List[dict]

    # Scoring
    scored_pairs: List[dict]
    failed_pairs: List[dict]
    generation_attempts: int

    # Deduplication
    deduped_pairs: List[dict]

    # Human review — pairs
    pairs_pending_review: List[dict]
    pairs_approved: List[dict]
    pairs_rejected: List[dict]

    # Export
    export_path: Optional[str]
    stats: dict

    # Diagnostics — last error message from a node (surfaced to UI log)
    last_error: Optional[str]


def build_graph():
    graph = StateGraph(PipelineState)

    # Register nodes
    graph.add_node("pdf_ingest", pdf_ingest_node)
    graph.add_node("search", search_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("chunk", chunk_node)
    graph.add_node("human_review_chunks", human_review_chunks_node)
    graph.add_node("store_chunks", store_chunks_node)
    graph.add_node("generate", generate_node)
    graph.add_node("score", score_node)
    graph.add_node("deduplicate", deduplicate_node)
    graph.add_node("human_review_pairs", human_review_pairs_node)
    graph.add_node("export", export_node)

    # Entry: branch directly from START — no passthrough node needed
    graph.add_conditional_edges(
        START,
        route_source,
        {
            "pdf": "pdf_ingest",
            "web": "search",
        }
    )

    # PDF path: ingest (includes chunking) → review
    graph.add_edge("pdf_ingest", "human_review_chunks")

    # Web path: search → scrape → chunk → review
    graph.add_edge("search", "scrape")
    graph.add_edge("scrape", "chunk")
    graph.add_edge("chunk", "human_review_chunks")

    # After chunk review: store or end
    graph.add_conditional_edges(
        "human_review_chunks",
        route_after_chunk_review,
        {"store": "store_chunks", "end": END}
    )

    graph.add_edge("store_chunks", "generate")
    graph.add_edge("generate", "score")

    # After scoring: retry or continue
    graph.add_conditional_edges(
        "score",
        route_after_scoring,
        {"retry": "generate", "continue": "deduplicate"}
    )

    graph.add_edge("deduplicate", "human_review_pairs")

    # After pair review: export or end
    graph.add_conditional_edges(
        "human_review_pairs",
        route_after_pair_review,
        {"export": "export", "end": END}
    )

    graph.add_edge("export", END)

    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["human_review_chunks", "human_review_pairs"],
    )
