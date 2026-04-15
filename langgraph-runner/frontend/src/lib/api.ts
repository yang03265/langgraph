import type { AnthropicMessage, AnthropicResponse, AnthropicToolDef } from '../types'

interface CallClaudeParams {
  system: string
  messages: AnthropicMessage[]
  tools?: AnthropicToolDef[]
  model?: string
  signal?: AbortSignal
}

export async function callClaude({
  system,
  messages,
  tools,
  model = 'mistralai/devstral-2-123b-instruct-2512',
  signal,
}: CallClaudeParams): Promise<AnthropicResponse> {
  const body: Record<string, unknown> = {
    model,
    max_tokens: 1000,
    system,
    messages,
  }
  if (tools && tools.length > 0) body.tools = tools

  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`API error ${res.status}: ${detail}`)
  }

  return res.json() as Promise<AnthropicResponse>
}

// Convert AgentConfig tool defs → Anthropic tool schema format
import type { ToolDef } from '../types'

export function configToAnthropicTools(tools: ToolDef[] = []): AnthropicToolDef[] {
  return tools.map(t => ({
    name: t.name,
    description: t.description,
    input_schema: {
      type: 'object' as const,
      properties: Object.fromEntries(
        t.params.map(p => [p, { type: 'string', description: p }])
      ),
      required: t.params,
    },
  }))
}

// Normalize tool names → stable graph node IDs
export function toolNodeName(name: string): string {
  return name.replace('send_notification', 'notify')
}
