// ─── Config Schema ─────────────────────────────────────────────────────────

export type AgentPattern = 'react' | 'supervisor' | 'parallel' | 'hitl'

export interface ToolDef {
  name: string
  description: string
  params: string[]
  requires_approval?: boolean
}

export interface WorkerDef {
  system_prompt: string
  tools: string[]
}

export interface Checkpoint {
  after_node?: string
  before_tool?: string
  prompt: string
}

export interface AgentConfig {
  pattern: AgentPattern
  model: string
  name: string
  description?: string
  system_prompt: string
  tools?: ToolDef[]
  max_iterations?: number
  stop_condition?: string
  // supervisor-specific
  supervisor?: { system_prompt: string; workers: string[] }
  workers?: Record<string, WorkerDef>
  max_rounds?: number
  // parallel-specific
  parallel_fan_out?: boolean
  merge_strategy?: string
  // hitl-specific
  hitl_enabled?: boolean
  checkpoints?: Checkpoint[]
}

// ─── Anthropic API ─────────────────────────────────────────────────────────

export interface AnthropicToolDef {
  name: string
  description: string
  input_schema: {
    type: 'object'
    properties: Record<string, { type: string; description: string }>
    required: string[]
  }
}

export interface ContentBlock {
  type: 'text' | 'tool_use' | 'tool_result'
  text?: string
  id?: string
  name?: string
  input?: Record<string, string>
  tool_use_id?: string
  content?: string
}

export interface AnthropicMessage {
  role: 'user' | 'assistant'
  content: string | ContentBlock[]
}

export interface AnthropicResponse {
  id: string
  type: string
  role: string
  content: ContentBlock[]
  model: string
  stop_reason: string
  usage: { input_tokens: number; output_tokens: number }
}

// ─── Trace Events ──────────────────────────────────────────────────────────

export type TraceTag =
  | 'NODE' | 'TOOL' | 'ROUTER' | 'HITL'
  | 'WORKER' | 'PARALLEL' | 'STATE' | 'ERROR' | 'ANSWER'

export type TraceTagClass =
  | 'tag-node' | 'tag-tool' | 'tag-router' | 'tag-hitl'
  | 'tag-worker' | 'tag-parallel' | 'tag-state' | 'tag-error' | 'tag-answer'

export interface TraceEvent {
  id: string
  tag: TraceTag
  tagClass: TraceTagClass
  content: string       // may contain safe HTML (strong, code tags)
  elapsed: string
  isAnswer?: boolean
}

export type CheckpointDecision = 'approve' | 'reject'

export interface HITLCheckpointEvent {
  id: string
  question: string
  resolved: boolean
  decision?: CheckpointDecision
}

// ─── Run State ─────────────────────────────────────────────────────────────

export type RunStatus = 'idle' | 'running' | 'done' | 'error' | 'stopped'

export interface RunState {
  status: RunStatus
  stepCount: number
  tokenCount: number
  elapsedMs: number | null
  activeNode: string | null
}
