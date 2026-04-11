# Synthetic Data Curation Pipeline

A multi-agent LangGraph workflow that generates high-quality instruction-following datasets grounded in real web content.

## Architecture

```
seed topic
  └─→ Search (DuckDuckGo top 10)
        └─→ Scraper (parallel fetch)
              └─→ Chunker
                    └─→ [HUMAN REVIEW] — approve/reject chunks
                          └─→ Vector Store (ChromaDB)
                                └─→ Generator Agent (RAG → Google Gemini)
                                      └─→ Quality Scorer (LLM judge)
                                            ├─→ [fail] → retry Generator
                                            └─→ [pass] → Deduplication
                                                          └─→ [HUMAN REVIEW] — approve/reject pairs
                                                                └─→ Export (JSONL)
```

## Key LangGraph Concepts Demonstrated

- **Stateful multi-step orchestration** — typed `PipelineState` flows through all nodes
- **Conditional edges** — score thresholds route to retry or continue; human decisions route to export or end
- **Human-in-the-loop** — `interrupt_before` pauses graph at both review nodes; `update_state` resumes with human decisions
- **Cycles** — generator → scorer → back to generator if quality threshold not met (max 3 attempts)
- **MemorySaver checkpointing** — full state persisted across interrupts

## Setup

```bash
pip install -r requirements.txt
```

## Usage

**Streamlit UI (recommended):**
```bash
streamlit run app.py
```
Then open http://localhost:8501, enter your Google API key and topic.

**CLI (no UI):**
```bash
python main.py --topic "Kubernetes pod scheduling" --api-key your_key_here
# or via env var: export GOOGLE_API_KEY=your_key_here
```

## Human Review Commands

**Chunk review** (before vector store):
- `a` — approve chunk
- `r` — reject chunk
- `s` — approve this and all remaining
- `q` — reject this and all remaining

**Pair review** (before export):
- `a` — approve pair
- `r` — reject pair
- `e` — edit instruction, then approve
- `s` — approve this and all remaining
- `q` — reject this and all remaining

## Output Format

JSONL file in `data/output/`, compatible with Axolotl, Unsloth, and HuggingFace datasets:

```json
{"instruction": "...", "input": "", "output": "..."}
```

## Project Structure

```
synthetic-data-pipeline/
├── main.py                  # Entry point + human-in-the-loop orchestration
├── requirements.txt
├── pipeline/
│   ├── graph.py             # LangGraph state + graph definition
│   ├── nodes.py             # All 10 pipeline nodes
│   ├── conditions.py        # Conditional edge routing
│   └── review.py            # CLI human review interface
└── data/
    ├── chroma/              # ChromaDB vector store (auto-created)
    └── output/              # Exported JSONL datasets (auto-created)
```
