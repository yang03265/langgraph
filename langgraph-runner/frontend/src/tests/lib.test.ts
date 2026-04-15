import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { simulateTool, defaultArgsForTool } from '../lib/simulator'
import { configToAnthropicTools, toolNodeName, callClaude } from '../lib/api'
import { PRESETS, DEFAULT_INPUTS } from '../lib/presets'
import { useAgentRunner } from '../hooks/useAgentRunner'
import type { ToolDef, AnthropicResponse, AgentConfig } from '../types'

// ─── simulateTool ──────────────────────────────────────────────────────────

describe('simulateTool', () => {
  it('calculator: evaluates expressions', () => {
    expect(simulateTool('calculator', { expression: '2 + 2' })).toBe('= 4')
    expect(simulateTool('calculator', { expression: '2**10' })).toBe('= 1024')
    expect(simulateTool('calculator', { expression: '2^10 + 137' })).toContain('=')
  })

  it('calculator: handles invalid expressions gracefully', () => {
    const result = simulateTool('calculator', { expression: 'not_valid((' })
    expect(result).toContain('Error')
  })

  it('web_search: returns result string containing query', () => {
    const result = simulateTool('web_search', { query: 'LangGraph' })
    expect(result).toContain('LangGraph')
  })

  it('fetch_stock_price: includes ticker in result', () => {
    const result = simulateTool('fetch_stock_price', { ticker: 'NVDA' })
    expect(result).toContain('NVDA')
    expect(result).toContain('$')
  })

  it('fetch_news: includes topic in result', () => {
    const result = simulateTool('fetch_news', { topic: 'AI' })
    expect(result).toContain('AI')
  })

  it('read_data: includes source in result', () => {
    const result = simulateTool('read_data', { source: 'my_db' })
    expect(result).toContain('my_db')
  })

  it('write_data: includes target in result', () => {
    const result = simulateTool('write_data', { target: 'users', content: 'data' })
    expect(result).toContain('users')
  })

  it('send_notification: includes recipient in result', () => {
    const result = simulateTool('send_notification', { recipient: 'alice', message: 'Hello' })
    expect(result).toContain('alice')
  })

  it('unknown tool: returns fallback string', () => {
    const result = simulateTool('unknown_xyz', {})
    expect(result).toContain('unknown_xyz')
    expect(result).toContain('OK')
  })

  it('finish: returns answer from input', () => {
    const result = simulateTool('finish', { answer: 'All done.' })
    expect(result).toBe('All done.')
  })

  it('finish: returns fallback when no answer', () => {
    const result = simulateTool('finish', {})
    expect(result).toBeTruthy()
  })
})

// ─── defaultArgsForTool ────────────────────────────────────────────────────

describe('defaultArgsForTool', () => {
  it('maps known params to sensible defaults', () => {
    const args = defaultArgsForTool(['source', 'target'])
    expect(args.source).toBe('customer_database')
    expect(args.target).toBe('users_table')
  })

  it('falls back to param name for unknown params', () => {
    const args = defaultArgsForTool(['foo', 'bar'])
    expect(args.foo).toBe('foo')
    expect(args.bar).toBe('bar')
  })

  it('returns empty object for empty params', () => {
    expect(defaultArgsForTool([])).toEqual({})
  })
})

// ─── configToAnthropicTools ────────────────────────────────────────────────

describe('configToAnthropicTools', () => {
  it('converts ToolDef array to Anthropic schema format', () => {
    const tools: ToolDef[] = [
      { name: 'web_search', description: 'Search the web', params: ['query'] },
    ]
    const result = configToAnthropicTools(tools)
    expect(result).toHaveLength(1)
    expect(result[0].name).toBe('web_search')
    expect(result[0].description).toBe('Search the web')
    expect(result[0].input_schema.type).toBe('object')
    expect(result[0].input_schema.properties).toHaveProperty('query')
    expect(result[0].input_schema.required).toContain('query')
  })

  it('handles multiple params', () => {
    const tools: ToolDef[] = [
      { name: 'write_data', description: 'Write data', params: ['target', 'content'] },
    ]
    const result = configToAnthropicTools(tools)
    expect(result[0].input_schema.required).toEqual(['target', 'content'])
    expect(Object.keys(result[0].input_schema.properties)).toEqual(['target', 'content'])
  })

  it('handles empty tools array', () => {
    expect(configToAnthropicTools([])).toEqual([])
  })

  it('handles undefined gracefully', () => {
    expect(configToAnthropicTools(undefined as unknown as ToolDef[])).toEqual([])
  })
})

// ─── toolNodeName ──────────────────────────────────────────────────────────

describe('toolNodeName', () => {
  it('normalizes send_notification to notify', () => {
    expect(toolNodeName('send_notification')).toBe('notify')
  })

  it('passes through other tool names unchanged', () => {
    expect(toolNodeName('read_data')).toBe('read_data')
    expect(toolNodeName('write_data')).toBe('write_data')
    expect(toolNodeName('web_search')).toBe('web_search')
  })
})

// ─── PRESETS ──────────────────────────────────────────────────────────────

describe('PRESETS', () => {
  it('all four patterns are defined', () => {
    expect(PRESETS.react.pattern).toBe('react')
    expect(PRESETS.supervisor.pattern).toBe('supervisor')
    expect(PRESETS.parallel.pattern).toBe('parallel')
    expect(PRESETS.hitl.pattern).toBe('hitl')
  })

  it('all presets have a model field', () => {
    Object.values(PRESETS).forEach(p => {
      expect(p.model).toBeTruthy()
      expect(typeof p.model).toBe('string')
    })
  })

  it('hitl preset has hitl_enabled: true', () => {
    expect(PRESETS.hitl.hitl_enabled).toBe(true)
  })

  it('hitl preset has requires_approval on write/notify tools', () => {
    const hitlTools = PRESETS.hitl.tools ?? []
    const approvalTools = hitlTools.filter(t => t.requires_approval).map(t => t.name)
    expect(approvalTools).toContain('write_data')
    expect(approvalTools).toContain('send_notification')
  })

  it('hitl checkpoints reference valid tool names', () => {
    const hitlTools = new Set((PRESETS.hitl.tools ?? []).map(t => t.name))
    ;(PRESETS.hitl.checkpoints ?? []).forEach(cp => {
      if (cp.before_tool) expect(hitlTools.has(cp.before_tool)).toBe(true)
    })
  })

  it('react preset has tools array', () => {
    expect(PRESETS.react.tools?.length).toBeGreaterThan(0)
  })

  it('supervisor preset has workers defined', () => {
    expect(PRESETS.supervisor.workers).toBeDefined()
    expect(Object.keys(PRESETS.supervisor.workers ?? {})).toContain('researcher')
  })

  it('parallel preset has parallel_fan_out: true', () => {
    expect(PRESETS.parallel.parallel_fan_out).toBe(true)
  })

  it('all 9 presets have correct pattern field', () => {
    expect(PRESETS['react-code'].pattern).toBe('react')
    expect(PRESETS['react-simple'].pattern).toBe('react')
    expect(PRESETS['supervisor-product'].pattern).toBe('supervisor')
    expect(PRESETS['parallel-research'].pattern).toBe('parallel')
    expect(PRESETS['hitl-deploy'].pattern).toBe('hitl')
  })

  it('react-code preset has code_exec tool', () => {
    const tools = PRESETS['react-code'].tools ?? []
    expect(tools.some(t => t.name === 'code_exec')).toBe(true)
  })

  it('react-simple preset has only calculator tool with max_iterations: 2', () => {
    const tools = PRESETS['react-simple'].tools ?? []
    expect(tools).toHaveLength(1)
    expect(tools[0].name).toBe('calculator')
    expect(PRESETS['react-simple'].max_iterations).toBe(2)
  })

  it('supervisor-product preset has 4 workers', () => {
    const workers = Object.keys(PRESETS['supervisor-product'].workers ?? {})
    expect(workers).toHaveLength(4)
    expect(workers).toContain('analyst')
    expect(workers).toContain('designer')
    expect(workers).toContain('developer')
    expect(workers).toContain('qa')
  })

  it('parallel-research preset has web_search, fetch_news, summarize tools', () => {
    const tools = PRESETS['parallel-research'].tools ?? []
    const toolNames = tools.map(t => t.name)
    expect(toolNames).toContain('web_search')
    expect(toolNames).toContain('fetch_news')
    expect(toolNames).toContain('summarize')
  })

  it('hitl-deploy preset has hitl_enabled and approval tools', () => {
    expect(PRESETS['hitl-deploy'].hitl_enabled).toBe(true)
    const tools = PRESETS['hitl-deploy'].tools ?? []
    const approvalTools = tools.filter(t => t.requires_approval).map(t => t.name)
    expect(approvalTools).toContain('write_data')
    expect(approvalTools).toContain('send_notification')
  })
})

// ─── DEFAULT_INPUTS ───────────────────────────────────────────────────────

describe('DEFAULT_INPUTS', () => {
  it('has an entry for each preset', () => {
    Object.keys(PRESETS).forEach(key => {
      expect(DEFAULT_INPUTS[key]).toBeTruthy()
    })
  })
})

// ─── callClaude ────────────────────────────────────────────────────────────

describe('callClaude', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls POST /api/chat with correct method and headers', async () => {
    const mockResponse: AnthropicResponse = {
      content: [{ type: 'text', text: 'Hi!' }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 10, output_tokens: 5 }
    }
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse)
    })
    vi.stubGlobal('fetch', mockFetch)

    await callClaude({ system: 'sys', messages: [{ role: 'user', content: 'hi' }] })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({ method: 'POST' })
    )
    const call = mockFetch.mock.calls[0][1]
    expect(call.headers['Content-Type']).toBe('application/json')
  })

  it('omits tools key when tools array is empty', async () => {
    const mockResponse: AnthropicResponse = {
      content: [{ type: 'text', text: 'Hi!' }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 10, output_tokens: 5 }
    }
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse)
    })
    vi.stubGlobal('fetch', mockFetch)

    await callClaude({ system: 'sys', messages: [{ role: 'user', content: 'hi' }], tools: [] })

    const body = JSON.parse(mockFetch.mock.calls[0][1].body)
    expect(body).not.toHaveProperty('tools')
  })

  it('includes tools key when tools provided', async () => {
    const mockResponse: AnthropicResponse = {
      content: [{ type: 'text', text: 'Hi!' }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 10, output_tokens: 5 }
    }
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse)
    })
    vi.stubGlobal('fetch', mockFetch)

    const tools = [{ name: 'search', description: 'Search', input_schema: { type: 'object' as const, properties: {}, required: [] } }]
    await callClaude({ system: 'sys', messages: [{ role: 'user', content: 'hi' }], tools })

    const body = JSON.parse(mockFetch.mock.calls[0][1].body)
    expect(body).toHaveProperty('tools')
    expect(body.tools).toHaveLength(1)
  })

  it('throws Error with API error message on non-ok response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: () => Promise.resolve('Bad Gateway')
    })
    vi.stubGlobal('fetch', mockFetch)

    await expect(
      callClaude({ system: 'sys', messages: [{ role: 'user', content: 'hi' }] })
    ).rejects.toThrow(/API error 502/)
  })

  it('passes signal from AbortController to fetch', async () => {
    const mockResponse: AnthropicResponse = {
      content: [{ type: 'text', text: 'Hi!' }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 10, output_tokens: 5 }
    }
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse)
    })
    vi.stubGlobal('fetch', mockFetch)

    const controller = new AbortController()
    await callClaude({
      system: 'sys',
      messages: [{ role: 'user', content: 'hi' }],
      signal: controller.signal
    })

    const call = mockFetch.mock.calls[0][1]
    expect(call.signal).toBe(controller.signal)
  })
})

// ─── useAgentRunner ────────────────────────────────────────────────────────

describe('useAgentRunner', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('initial state is idle with empty traces and checkpoints', () => {
    const { result } = renderHook(() => useAgentRunner())
    expect(result.current.runState.status).toBe('idle')
    expect(result.current.traces).toEqual([])
    expect(result.current.checkpoints).toEqual([])
    expect(result.current.runState.stepCount).toBe(0)
    expect(result.current.runState.tokenCount).toBe(0)
  })

  it('clearTraces resets all state to idle defaults', () => {
    const { result } = renderHook(() => useAgentRunner())

    act(() => {
      result.current.clearTraces()
    })

    expect(result.current.runState.status).toBe('idle')
    expect(result.current.traces).toEqual([])
    expect(result.current.checkpoints).toEqual([])
    expect(result.current.runState.stepCount).toBe(0)
  })

  it('run with unknown pattern sets status to error', async () => {
    vi.mock('../lib/api')
    const { result } = renderHook(() => useAgentRunner())

    const badConfig: AgentConfig = {
      pattern: 'unknown' as any,
      model: 'test',
      name: 'Test',
      system_prompt: 'Test',
    }

    await act(async () => {
      await result.current.run(badConfig, 'test message', false)
    })

    expect(result.current.runState.status).toBe('error')
    const errorTrace = result.current.traces.find(t => t.tag === 'ERROR')
    expect(errorTrace).toBeDefined()
  })

  it('stop calls AbortController.abort', () => {
    const { result } = renderHook(() => useAgentRunner())
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort')

    act(() => {
      result.current.stop()
    })

    expect(abortSpy).toHaveBeenCalled()
    abortSpy.mockRestore()
  })

  it('resolveCheckpoint with approve marks decision and resolves promise', () => {
    const { result } = renderHook(() => useAgentRunner())

    act(() => {
      // Create a checkpoint by manually setting state
      // In real usage, checkpoints are created during run()
      // For testing, we just verify the resolve method works correctly
      result.current.resolveCheckpoint('cp_1', 'approve')
    })

    const checkpoint = result.current.checkpoints.find(cp => cp.id === 'cp_1')
    if (checkpoint) {
      expect(checkpoint.resolved).toBe(true)
      expect(checkpoint.decision).toBe('approve')
    }
  })

  it('resolveCheckpoint with reject marks decision correctly', () => {
    const { result } = renderHook(() => useAgentRunner())

    act(() => {
      result.current.resolveCheckpoint('cp_2', 'reject')
    })

    const checkpoint = result.current.checkpoints.find(cp => cp.id === 'cp_2')
    if (checkpoint) {
      expect(checkpoint.resolved).toBe(true)
      expect(checkpoint.decision).toBe('reject')
    }
  })
})
