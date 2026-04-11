"""
app.py — Streamlit UI for the Synthetic Data Curation Pipeline
"""

import html
import streamlit as st
import threading
import queue
import time
import json
import os
from pathlib import Path

from pipeline.graph import build_graph
from pipeline.nodes import DATASET_TYPE_CONFIGS, reset_vectorstore, extract_pdf_text

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Synthetic Data Pipeline",
    page_icon="🧪",
    layout="wide",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    .stButton > button { border-radius: 6px; font-weight: 600; padding: 0.3rem 1.2rem; }
    .approve-btn > button { background-color: #16a34a; color: white; border: none; }
    .approve-btn > button:hover { background-color: #15803d; }
    .reject-btn > button { background-color: #dc2626; color: white; border: none; }
    .reject-btn > button:hover { background-color: #b91c1c; }
    .chunk-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem; }
    .pair-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem; }
    .score-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 700; }
    .log-box { background: #0f172a; color: #94a3b8; font-family: monospace; font-size: 0.8rem; padding: 1rem; border-radius: 8px; height: 320px; overflow-y: auto; }
    .dataset-badge { display: inline-block; background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 6px; padding: 2px 10px; font-size: 0.8rem; font-weight: 600; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

DEFAULTS = {
    "stage": "input", "logs": [], "graph": None, "thread_config": None,
    "chunks_pending": [], "chunks_approved": [], "chunks_rejected": [],
    "pairs_pending": [], "pairs_approved": [], "pairs_rejected": [],
    "export_path": None, "stats": {}, "topic": "",
    "source_type": "web", "dataset_type": "Instruction Following",
    # PDF state cached to survive Streamlit reruns without re-reading the file
    "_pdf_cache": {},   # {filename: (pdf_text, page_count)}
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

def log(msg: str):
    st.session_state.logs.append(msg)

def score_color(s: float) -> str:
    return "#16a34a" if s >= 8 else ("#d97706" if s >= 6 else "#dc2626")

def dataset_description(dt: str) -> str:
    """Single source of truth — pulled from DATASET_TYPE_CONFIGS."""
    return DATASET_TYPE_CONFIGS.get(dt, {}).get("description", "")

def render_log():
    """Render log panel with HTML-escaped entries to prevent injection."""
    logs_html = "<br>".join(html.escape(l) for l in st.session_state.logs[-30:])
    st.markdown(f'<div class="log-box">{logs_html}</div>', unsafe_allow_html=True)

def count_unique_nodes(logs: list, node_names: list) -> int:
    """Count how many distinct node names have appeared in logs (not total log lines).
    Prevents retry loops from inflating progress beyond 100%."""
    seen = set()
    for l in logs:
        for n in node_names:
            if f"✓ {n}" in l:
                seen.add(n)
    return len(seen)

# ── Pipeline runner functions (background threads) ────────────────────────────

def _log_node_event(rq: queue.Queue, node_name: str, update):
    """Log a node completion + any interesting summary info from its state update."""
    rq.put(("log", f"✓ {node_name}"))
    if not isinstance(update, dict):
        return
    if node_name == "generate":
        n = len(update.get("raw_pairs", []) or [])
        attempt = update.get("generation_attempts", 0)
        rq.put(("log", f"  → attempt {attempt}: {n} pairs generated"))
        err = update.get("last_error")
        if err:
            rq.put(("log", f"  ⚠ parse error: {err}"))
    elif node_name == "score":
        scored = update.get("scored_pairs", []) or []
        failed = update.get("failed_pairs", []) or []
        promoted = sum(1 for p in scored if p.get("below_threshold"))
        msg = f"  → {len(scored)} passed, {len(failed)} failed"
        if promoted:
            msg += f" ({promoted} promoted below threshold)"
        rq.put(("log", msg))
    elif node_name == "deduplicate":
        deduped = update.get("deduped_pairs", []) or []
        rq.put(("log", f"  → {len(deduped)} unique pairs"))


def run_to_chunk_review(initial_state: dict, api_key: str, rq: queue.Queue):
    os.environ["GOOGLE_API_KEY"] = api_key
    reset_vectorstore()
    try:
        graph = build_graph()
        thread_config = {"configurable": {"thread_id": f"pipeline-{int(time.time())}"}}
        for event in graph.stream(initial_state, config=thread_config):
            for node_name, update in event.items():
                _log_node_event(rq, node_name, update)
        state = graph.get_state(thread_config)
        rq.put(("chunk_review", {
            "graph": graph,
            "thread_config": thread_config,
            "chunks": state.values.get("chunks_pending_review", []),
        }))
    except Exception as e:
        rq.put(("error", str(e)))


def run_to_pair_review(graph, thread_config: dict, approved: list, rejected: list, api_key: str, rq: queue.Queue):
    os.environ["GOOGLE_API_KEY"] = api_key
    try:
        graph.update_state(
            thread_config,
            {"chunks_approved": approved, "chunks_rejected": rejected, "chunks_pending_review": []},
            as_node="human_review_chunks",
        )
        for event in graph.stream(None, config=thread_config):
            for node_name, update in event.items():
                _log_node_event(rq, node_name, update)
        state = graph.get_state(thread_config)
        rq.put(("pair_review", {"pairs": state.values.get("pairs_pending_review", [])}))
    except Exception as e:
        rq.put(("error", str(e)))


def run_to_export(graph, thread_config: dict, approved: list, rejected: list, api_key: str, rq: queue.Queue):
    os.environ["GOOGLE_API_KEY"] = api_key
    try:
        graph.update_state(
            thread_config,
            {"pairs_approved": approved, "pairs_rejected": rejected, "pairs_pending_review": []},
            as_node="human_review_pairs",
        )
        for event in graph.stream(None, config=thread_config):
            for node_name, update in event.items():
                _log_node_event(rq, node_name, update)
        state = graph.get_state(thread_config)
        rq.put(("done", {
            "export_path": state.values.get("export_path"),
            "stats": state.values.get("stats", {}),
        }))
    except Exception as e:
        rq.put(("error", str(e)))

# ── Layout ────────────────────────────────────────────────────────────────────

st.title("🧪 Synthetic Data Curation Pipeline")
st.caption("LangGraph · DuckDuckGo / PDF · ChromaDB · Google Gemini (gemini-2.5-flash) · Local MiniLM embeddings")

col_main, col_log = st.columns([2, 1])
with col_log:
    st.subheader("Pipeline Log")
    render_log()

# ── INPUT ─────────────────────────────────────────────────────────────────────

if st.session_state.stage == "input":
    with col_main:
        st.subheader("Configure Pipeline")

        api_key = st.text_input("Google API Key", type="password", placeholder="Enter your Google API key")
        st.divider()

        st.markdown("**Dataset Type**")
        dataset_type = st.selectbox("Dataset Type", list(DATASET_TYPE_CONFIGS.keys()), label_visibility="collapsed")
        st.caption(dataset_description(dataset_type))

        pair_count = st.number_input(
            "Target number of pairs per attempt",
            min_value=1, max_value=50, value=10, step=1,
            help="How many instruction-output pairs to ask the model to generate. "
                 "Final output may be smaller after scoring, dedup, and human review.",
        )
        st.divider()

        st.markdown("**Data Source**")
        source_opt = st.radio("Source", ["🌐 Web Search (DuckDuckGo)", "📄 PDF Upload"], horizontal=True, label_visibility="collapsed")
        is_pdf = source_opt.startswith("📄")

        topic = st.text_input(
            "Topic / Description",
            placeholder="e.g. What this document is about" if is_pdf else "e.g. LangGraph multi-agent systems",
            help="Used to query the vector store during generation." if is_pdf else "Used to search DuckDuckGo.",
        )

        pdf_text, pdf_filename, pdf_page_count = None, None, None
        if is_pdf:
            uploaded = st.file_uploader("Upload PDF", type=["pdf"])
            if uploaded:
                cache = st.session_state._pdf_cache
                if uploaded.name in cache:
                    # Use cached extraction — avoids re-reading exhausted file cursor on rerun
                    pdf_text, pdf_page_count = cache[uploaded.name]
                    pdf_filename = uploaded.name
                    st.success(f"✓ **{pdf_filename}** — {pdf_page_count} pages, {len(pdf_text):,} chars")
                else:
                    # First time seeing this file — extract and cache
                    try:
                        raw = uploaded.read()
                        pdf_text, pdf_page_count = extract_pdf_text(raw)
                        pdf_filename = uploaded.name
                        st.session_state._pdf_cache[uploaded.name] = (pdf_text, pdf_page_count)
                        st.success(f"✓ **{pdf_filename}** — {pdf_page_count} pages, {len(pdf_text):,} chars extracted")
                    except ValueError as e:
                        st.error(f"PDF error: {e}")
                        pdf_text = None

        can_start = bool(api_key and topic and (not is_pdf or pdf_text))

        if st.button("🚀 Start Pipeline", type="primary"):
            if not can_start:
                if not api_key:
                    st.error("Please enter your Google API key.")
                if not topic:
                    st.error("Please enter a topic or description.")
                if is_pdf and not pdf_text:
                    st.error("Please upload a valid, readable PDF.")
            else:
                st.session_state.update({
                    "topic": topic,
                    "source_type": "pdf" if is_pdf else "web",
                    "dataset_type": dataset_type,
                    "pair_count": int(pair_count),
                    "_api_key": api_key,
                    "stage": "running",
                    "logs": [],
                    "_rq": None,  # clear stale queue from any previous run
                    # Reset review state
                    "chunks_pending": [], "chunks_approved": [], "chunks_rejected": [],
                    "pairs_pending": [], "pairs_approved": [], "pairs_rejected": [],
                })
                log(f"Topic: {topic}")
                log(f"Source: {'PDF — ' + (pdf_filename or '') if is_pdf else 'Web search'}")
                log(f"Dataset type: {dataset_type}")
                log(f"Target pairs: {int(pair_count)}")

                initial_state = {
                    "seed_topic": topic,
                    "source_type": "pdf" if is_pdf else "web",
                    "dataset_type": dataset_type,
                    "pair_count": int(pair_count),
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
                rq = queue.Queue()
                st.session_state["_rq"] = rq
                threading.Thread(target=run_to_chunk_review, args=(initial_state, api_key, rq), daemon=True).start()
                st.rerun()

# ── RUNNING ───────────────────────────────────────────────────────────────────

elif st.session_state.stage == "running":
    with col_main:
        st.subheader("Running Pipeline...")
        st.markdown(f'<span class="dataset-badge">{st.session_state.dataset_type}</span>', unsafe_allow_html=True)
        src = "PDF" if st.session_state.source_type == "pdf" else "Web"
        st.info(f"**Topic:** {st.session_state.topic}  ·  **Source:** {src}")

        progress_nodes = ["pdf_ingest"] if st.session_state.source_type == "pdf" else ["search", "scrape", "chunk"]
        done = count_unique_nodes(st.session_state.logs, progress_nodes)
        st.progress(min(done / len(progress_nodes), 0.99), text=f"{done}/{len(progress_nodes)} nodes completed...")

    rq = st.session_state.get("_rq")
    if rq:
        try:
            while True:
                msg_type, payload = rq.get_nowait()
                if msg_type == "log":
                    log(payload)
                elif msg_type == "chunk_review":
                    chunks = payload["chunks"]
                    if not chunks:
                        # PDF produced zero chunks — error before entering review
                        log("❌ No chunks produced — check that PDF is text-based, not scanned")
                        st.session_state.stage = "input"
                    else:
                        st.session_state.graph = payload["graph"]
                        st.session_state.thread_config = payload["thread_config"]
                        st.session_state.chunks_pending = chunks
                        st.session_state.stage = "chunk_review"
                        log(f"⏸ Chunk review: {len(chunks)} chunks ready")
                    st.rerun()
                elif msg_type == "error":
                    st.error(f"Pipeline error: {payload}")
                    log(f"❌ {payload}")
                    st.session_state.stage = "input"
                    st.rerun()
        except queue.Empty:
            pass
    time.sleep(1)
    st.rerun()

# ── CHUNK REVIEW ──────────────────────────────────────────────────────────────

elif st.session_state.stage == "chunk_review":
    with col_main:
        chunks = st.session_state.chunks_pending
        approved = st.session_state.chunks_approved
        rejected = st.session_state.chunks_rejected
        reviewed_ids = {c["id"] for c in approved + rejected}
        pending = [c for c in chunks if c["id"] not in reviewed_ids]

        st.subheader(f"📋 Review Chunks — {len(approved)+len(rejected)}/{len(chunks)} reviewed")
        st.markdown(f'<span class="dataset-badge">{st.session_state.dataset_type}</span>', unsafe_allow_html=True)
        src = "PDF" if st.session_state.source_type == "pdf" else "Web"
        st.caption(f"Source: **{src}** · Approve chunks to store in the vector store.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Pending", len(pending))
        c2.metric("Approved", len(approved))
        c3.metric("Rejected", len(rejected))

        if pending:
            chunk = pending[0]
            src_line = "" if chunk["url"].startswith("pdf://") else f'<small style="color:#64748b">{html.escape(chunk["url"])}</small><br>'
            chunk_text_escaped = html.escape(chunk["text"][:800])
            st.markdown(
                f'<div class="chunk-card"><strong>{html.escape(chunk["title"])}</strong><br>{src_line}'
                f'<small style="color:#94a3b8">Chunk {chunk["chunk_index"]+1}</small>'
                f'<hr style="margin:0.5rem 0;border-color:#e2e8f0">'
                f'<pre style="white-space:pre-wrap;font-size:0.85rem;margin:0">'
                f'{chunk_text_escaped}{"..." if len(chunk["text"])>800 else ""}</pre></div>',
                unsafe_allow_html=True,
            )

            b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
            with b1:
                st.markdown('<div class="approve-btn">', unsafe_allow_html=True)
                if st.button("✓ Approve", key=f"ac_{chunk['id']}"):
                    st.session_state.chunks_approved.append(chunk)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with b2:
                st.markdown('<div class="reject-btn">', unsafe_allow_html=True)
                if st.button("✗ Reject", key=f"rc_{chunk['id']}"):
                    st.session_state.chunks_rejected.append(chunk)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with b3:
                if st.button("✓ Approve All Remaining", key=f"ar_all_{chunk['id']}"):
                    st.session_state.chunks_approved.extend(pending)
                    st.rerun()
            with b4:
                if st.button("✗ Reject All Remaining", key=f"rr_all_{chunk['id']}"):
                    st.session_state.chunks_rejected.extend(pending)
                    st.rerun()

        else:
            st.success(f"All chunks reviewed! {len(approved)} approved, {len(rejected)} rejected.")
            if not approved:
                st.error("No chunks approved — cannot continue.")
                if st.button("↩ Start Over"):
                    for k in ["stage", "logs", "chunks_pending", "chunks_approved", "chunks_rejected",
                              "pairs_pending", "pairs_approved", "pairs_rejected", "graph", "thread_config", "_rq"]:
                        st.session_state.pop(k, None)
                    st.rerun()
            else:
                if st.button("▶ Continue to Generation", type="primary"):
                    st.session_state.stage = "generating"
                    log(f"Generating {st.session_state.dataset_type} pairs from {len(approved)} chunks")
                    rq = queue.Queue()
                    st.session_state["_rq"] = rq
                    threading.Thread(
                        target=run_to_pair_review,
                        args=(st.session_state.graph, st.session_state.thread_config,
                              approved, rejected, st.session_state._api_key, rq),
                        daemon=True,
                    ).start()
                    st.rerun()

# ── GENERATING ────────────────────────────────────────────────────────────────

elif st.session_state.stage == "generating":
    with col_main:
        st.subheader("⚙️ Generating Pairs...")
        st.markdown(f'<span class="dataset-badge">{st.session_state.dataset_type}</span>', unsafe_allow_html=True)
        st.info("Storing chunks → generating → scoring → deduplicating...")

        gen_nodes = ["store_chunks", "generate", "score", "deduplicate"]
        # count_unique_nodes prevents retry loops from inflating the counter
        done = count_unique_nodes(st.session_state.logs, gen_nodes)
        st.progress(min(done / len(gen_nodes), 0.99), text=f"{done}/{len(gen_nodes)} nodes completed...")

    rq = st.session_state.get("_rq")
    if rq:
        try:
            while True:
                msg_type, payload = rq.get_nowait()
                if msg_type == "log":
                    log(payload)
                elif msg_type == "pair_review":
                    pairs = payload["pairs"]
                    if not pairs:
                        # All pairs failed scoring — nothing to review
                        log("❌ No pairs passed scoring after all retries — try different content or topic")
                        st.session_state.stage = "input"
                    else:
                        st.session_state.pairs_pending = pairs
                        st.session_state.stage = "pair_review"
                        log(f"⏸ Pair review: {len(pairs)} pairs ready")
                    st.rerun()
                elif msg_type == "error":
                    st.error(f"Pipeline error: {payload}")
                    log(f"❌ {payload}")
                    st.session_state.stage = "input"
                    st.rerun()
        except queue.Empty:
            pass
    time.sleep(1)
    st.rerun()

# ── PAIR REVIEW ───────────────────────────────────────────────────────────────

elif st.session_state.stage == "pair_review":
    with col_main:
        pairs = st.session_state.pairs_pending
        approved = st.session_state.pairs_approved
        rejected = st.session_state.pairs_rejected
        reviewed_ids = {p["id"] for p in approved + rejected}
        pending = [p for p in pairs if p["id"] not in reviewed_ids]

        st.subheader(f"🔍 Review Pairs — {len(approved)+len(rejected)}/{len(pairs)} reviewed")
        st.markdown(f'<span class="dataset-badge">{st.session_state.dataset_type}</span>', unsafe_allow_html=True)
        st.caption("Review each pair before export. You can edit the instruction before approving.")

        if any(p.get("below_threshold") for p in pairs):
            st.warning(
                "⚠️ No pairs met the 6.0 quality threshold after 3 retries. "
                "Showing the highest-scoring generated pairs for manual review — "
                "review carefully and reject anything that doesn't look grounded."
            )

        c1, c2, c3 = st.columns(3)
        c1.metric("Pending", len(pending))
        c2.metric("Approved", len(approved))
        c3.metric("Rejected", len(rejected))

        if pending:
            pair = pending[0]
            score = pair.get("avg_score")
            score_html = (
                f'<span class="score-badge" style="background:{score_color(score)};color:white">'
                f'Score: {score:.1f}/10</span>'
            ) if isinstance(score, float) else ""

            st.markdown(f'<div class="pair-card">{score_html}', unsafe_allow_html=True)
            edited = st.text_area("Instruction", value=pair["instruction"], key=f"ins_{pair['id']}", height=80)
            if pair.get("input"):
                st.text_area("Input", value=pair["input"], key=f"inp_{pair['id']}", height=100)
            st.text_area("Output", value=pair["output"], key=f"out_{pair['id']}", height=200, disabled=True)

            if pair.get("scores"):
                s = pair["scores"]
                s1, s2, s3 = st.columns(3)
                s1.metric("Accuracy", f"{s.get('accuracy')}/10")
                s2.metric("Clarity", f"{s.get('clarity')}/10")
                s3.metric("Completeness", f"{s.get('completeness')}/10")
                st.caption(f"Feedback: {s.get('feedback', '')}")
            st.markdown('</div>', unsafe_allow_html=True)

            b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
            with b1:
                st.markdown('<div class="approve-btn">', unsafe_allow_html=True)
                if st.button("✓ Approve", key=f"ap_{pair['id']}"):
                    p = dict(pair)
                    p["instruction"] = edited
                    st.session_state.pairs_approved.append(p)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with b2:
                st.markdown('<div class="reject-btn">', unsafe_allow_html=True)
                if st.button("✗ Reject", key=f"rp_{pair['id']}"):
                    st.session_state.pairs_rejected.append(pair)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            with b3:
                if st.button("✓ Approve All Remaining", key=f"ap_all_{pair['id']}"):
                    st.session_state.pairs_approved.extend(pending)
                    st.rerun()
            with b4:
                if st.button("✗ Reject All Remaining", key=f"rp_all_{pair['id']}"):
                    st.session_state.pairs_rejected.extend(pending)
                    st.rerun()

        else:
            st.success(f"All pairs reviewed! {len(approved)} approved, {len(rejected)} rejected.")
            if not approved:
                st.error("No pairs approved. Nothing to export.")
            else:
                if st.button("💾 Export Dataset", type="primary"):
                    st.session_state.stage = "exporting"
                    rq = queue.Queue()
                    st.session_state["_rq"] = rq
                    threading.Thread(
                        target=run_to_export,
                        args=(st.session_state.graph, st.session_state.thread_config,
                              approved, rejected, st.session_state._api_key, rq),
                        daemon=True,
                    ).start()
                    st.rerun()

# ── EXPORTING ─────────────────────────────────────────────────────────────────

elif st.session_state.stage == "exporting":
    with col_main:
        st.subheader("💾 Exporting...")
        st.info("Writing approved pairs to JSONL...")

    rq = st.session_state.get("_rq")
    if rq:
        try:
            while True:
                msg_type, payload = rq.get_nowait()
                if msg_type == "log":
                    log(payload)
                elif msg_type == "done":
                    st.session_state.export_path = payload["export_path"]
                    st.session_state.stats = payload["stats"]
                    st.session_state.stage = "done"
                    st.rerun()
                elif msg_type == "error":
                    st.error(f"Export error: {payload}")
        except queue.Empty:
            pass
    time.sleep(1)
    st.rerun()

# ── DONE ──────────────────────────────────────────────────────────────────────

elif st.session_state.stage == "done":
    with col_main:
        st.subheader("✅ Pipeline Complete")
        st.markdown(f'<span class="dataset-badge">{st.session_state.dataset_type}</span>', unsafe_allow_html=True)
        stats = st.session_state.stats

        c1, c2, c3, c4 = st.columns(4)
        src_lbl = "PDF Pages" if st.session_state.source_type == "pdf" else "Pages Scraped"
        c1.metric(src_lbl, stats.get("pages_scraped", 0))
        c2.metric("Chunks Stored", stats.get("chunks_approved", 0))
        c3.metric("Pairs Generated", stats.get("pairs_generated", 0))
        c4.metric("Pairs Exported", stats.get("pairs_exported", 0))

        path = st.session_state.export_path
        if path and Path(path).exists():
            st.success(f"Saved: `{path}`")
            content = open(path).read()
            st.download_button("⬇️ Download JSONL", content, Path(path).name, "application/json")

            st.subheader("Preview")
            for i, line in enumerate(content.strip().split("\n")[:3]):
                pair = json.loads(line)
                with st.expander(f"Pair {i+1}: {pair['instruction'][:70]}..."):
                    st.markdown(f"**Instruction:** {pair['instruction']}")
                    if pair.get("input"):
                        st.markdown(f"**Input:** {pair['input']}")
                    st.markdown(f"**Output:** {pair['output']}")

        if st.button("🔄 Run Again"):
            for k in ["stage", "logs", "graph", "thread_config", "_api_key", "_rq",
                      "chunks_pending", "chunks_approved", "chunks_rejected",
                      "pairs_pending", "pairs_approved", "pairs_rejected",
                      "export_path", "stats", "source_type", "dataset_type", "_pdf_cache"]:
                st.session_state.pop(k, None)
            st.rerun()
