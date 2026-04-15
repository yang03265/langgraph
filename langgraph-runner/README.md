# LangGraph Config Runner

A config-driven LangGraph agent runner with a FastAPI backend and React/Vite frontend. Define agent graphs in JSON, execute them live against NVIDIA's API (with Mistral models), and watch the trace stream in real time.

Supports four agent patterns: **ReAct**, **Supervisor/Workers**, **Parallel tool execution**, and **Human-in-the-Loop**.

---

## Project Structure

```
langgraph-runner/
├── backend/
│   ├── main.py              # FastAPI app — NVIDIA API proxy
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LeftPanel.tsx    # Config editor, input, graph viz tabs
│   │   │   └── TraceStream.tsx  # Execution trace + HITL checkpoints
│   │   ├── hooks/
│   │   │   └── useAgentRunner.ts  # All four agent pattern runners
│   │   ├── lib/
│   │   │   ├── api.ts           # /api/chat client + tool schema helpers
│   │   │   ├── presets.ts       # Built-in config presets
│   │   │   └── simulator.ts     # Simulated tool responses
│   │   ├── types/
│   │   │   └── index.ts         # Shared TypeScript types
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.ts
├── configs/                 # Example JSON config files
│   ├── react.json
│   ├── supervisor.json
│   ├── parallel.json
│   └── hitl.json
├── tests/
│   └── test_backend.py      # FastAPI proxy tests
└── .env.example
```

---

## Quickstart

### 1. Clone and configure

```bash
git clone <repo>
cd langgraph-runner
cp .env.example .env
# Edit .env and add your NVIDIA_API_KEY
# Get a free key at: https://build.nvidia.com/
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Check `/health` to confirm.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api/*` to the backend automatically.

---

## Usage

1. **CONFIG tab** — Select a preset or paste your own JSON config. The graph visualization updates live as you edit.
2. **INPUT tab** — Enter a task for the agent. Toggle **HITL** to enable human approval checkpoints.
3. Click **▶ Run Agent** — the execution trace streams on the right panel.
4. For HITL runs, **Approve** or **Reject** each checkpoint inline in the trace.
5. Use **■ Stop** (visible in the run bar or the execution header) to abort a running agent.

---

## Config Schema

All configs share these top-level fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | `react` \| `supervisor` \| `parallel` \| `hitl` | ✓ | Agent execution pattern |
| `model` | string | ✓ | Anthropic model string |
| `name` | string | ✓ | Display name |
| `system_prompt` | string | ✓ | System prompt for the agent |
| `tools` | ToolDef[] | — | Tools available to the agent |

See `configs/` for full examples of each pattern.

### ToolDef

```json
{
  "name": "web_search",
  "description": "Search the web",
  "params": ["query"],
  "requires_approval": false
}
```

### HITL Checkpoints

```json
{
  "checkpoints": [
    { "after_node": "plan",        "prompt": "Approve the plan?" },
    { "before_tool": "write_data", "prompt": "Approve write operation?" }
  ]
}
```

---

## Running Tests

### Backend

```bash
cd backend
pytest ../tests/test_backend.py -v
```

### Frontend

```bash
cd frontend
npm test
```

---

## Architecture Notes

- **NVIDIA API proxy.** The frontend calls `/api/chat` on the FastAPI backend, which injects the `NVIDIA_API_KEY` from the environment before forwarding to `integrate.api.nvidia.com/v1`. The backend implements OpenAI-compatible request/response conversion to normalize the NVIDIA API into an Anthropic-like format.
- **API key never reaches the browser.** Sensitive credentials stay server-side. The frontend uses only relative `/api/*` paths.
- **Tool execution is simulated.** The `simulator.ts` module returns realistic mock responses. To connect real tools, replace the handlers in `simulateTool()` with actual API calls.
- **Configs are plain JSON.** Any valid JSON matching the schema can be pasted into the editor — no build step, no code changes needed to define a new agent.
- **Abort is wired end-to-end.** The `AbortController` in `useAgentRunner` passes its signal to every agent loop, allowing the Stop button to interrupt long-running executions immediately.
