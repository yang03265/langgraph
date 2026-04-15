import { useState, useRef, useCallback } from 'react'
import type {
  AgentConfig, TraceEvent, TraceTag, TraceTagClass,
  HITLCheckpointEvent, RunState, AnthropicMessage, ContentBlock,
} from '../types'
import { callClaude, configToAnthropicTools, toolNodeName } from '../lib/api'
import { simulateTool, defaultArgsForTool } from '../lib/simulator'

// ─── helpers ───────────────────────────────────────────────────────────────

const TAG_CLASS: Record<TraceTag, TraceTagClass> = {
  NODE: 'tag-node', TOOL: 'tag-tool', ROUTER: 'tag-router', HITL: 'tag-hitl',
  WORKER: 'tag-worker', PARALLEL: 'tag-parallel', STATE: 'tag-state',
  ERROR: 'tag-error', ANSWER: 'tag-answer',
}

let _idSeq = 0
const uid = () => String(++_idSeq)
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

// ─── hook ──────────────────────────────────────────────────────────────────

export function useAgentRunner() {
  const [traces, setTraces] = useState<TraceEvent[]>([])
  const [checkpoints, setCheckpoints] = useState<HITLCheckpointEvent[]>([])
  const [runState, setRunState] = useState<RunState>({
    status: 'idle', stepCount: 0, tokenCount: 0, elapsedMs: null, activeNode: null,
  })

  const abortRef = useRef<AbortController | null>(null)
  const startTimeRef = useRef<number>(0)
  const tokenCountRef = useRef(0)
  // Map checkpoint id → resolve function so the UI can unblock the runner
  const checkpointResolvers = useRef<Map<string, (d: 'approve' | 'reject') => void>>(new Map())

  // ── state helpers ─────────────────────────────────────────────────────────

  const addTrace = useCallback((tag: TraceTag, content: string, isAnswer = false) => {
    const elapsed = ((Date.now() - startTimeRef.current) / 1000).toFixed(1) + 's'
    const event: TraceEvent = { id: uid(), tag, tagClass: TAG_CLASS[tag], content, elapsed, isAnswer }
    setTraces(prev => [...prev, event])
    setRunState(prev => ({ ...prev, stepCount: prev.stepCount + 1 }))
    return event
  }, [])

  const setActiveNode = useCallback((node: string | null) => {
    setRunState(prev => ({ ...prev, activeNode: node }))
  }, [])

  const addTokens = useCallback((used: number) => {
    tokenCountRef.current += used
    setRunState(prev => ({ ...prev, tokenCount: tokenCountRef.current }))
  }, [])

  // ── HITL checkpoint ────────────────────────────────────────────────────────
  // Returns a Promise that resolves when the user clicks Approve or Reject

  const requestCheckpoint = useCallback((question: string): Promise<'approve' | 'reject'> => {
    const id = uid()
    const cp: HITLCheckpointEvent = { id, question, resolved: false }
    setCheckpoints(prev => [...prev, cp])
    return new Promise(resolve => {
      checkpointResolvers.current.set(id, resolve)
    })
  }, [])

  const resolveCheckpoint = useCallback((id: string, decision: 'approve' | 'reject') => {
    setCheckpoints(prev =>
      prev.map(cp => cp.id === id ? { ...cp, resolved: true, decision } : cp)
    )
    const resolver = checkpointResolvers.current.get(id)
    if (resolver) {
      resolver(decision)
      checkpointResolvers.current.delete(id)
    }
  }, [])

  // ── API wrapper ────────────────────────────────────────────────────────────

  const claude = useCallback(async (
    system: string,
    messages: AnthropicMessage[],
    tools = configToAnthropicTools([]),
    model = 'gemini-2.0-flash',
  ) => {
    const data = await callClaude({
      system, messages, tools, model,
      signal: abortRef.current?.signal,
    })
    addTokens((data.usage?.input_tokens ?? 0) + (data.usage?.output_tokens ?? 0))
    return data
  }, [addTokens])

  // ── agent runners ─────────────────────────────────────────────────────────

  async function runReAct(cfg: AgentConfig, userMessage: string) {
    const tools = configToAnthropicTools(cfg.tools ?? [])
    const model = cfg.model
    const messages: AnthropicMessage[] = [{ role: 'user', content: userMessage }]
    let iterations = 0

    addTrace('NODE', 'Entering <code>agent</code> — initial reasoning pass')
    setActiveNode('agent')

    while (iterations < (cfg.max_iterations ?? 5)) {
      if (abortRef.current?.signal.aborted) break
      iterations++
      const data = await claude(cfg.system_prompt, messages, tools, model)
      const texts = data.content.filter(b => b.type === 'text')
      const toolUses = data.content.filter(b => b.type === 'tool_use')

      if (texts.length) {
        addTrace('NODE', `<strong>Thought:</strong> ${texts.map(b => b.text).join(' ')}`)
      }

      if (!toolUses.length || data.stop_reason === 'end_turn') {
        addTrace('ANSWER', texts.map(b => b.text).join('\n') || 'Task complete.', true)
        break
      }

      const toolResults: ContentBlock[] = []
      for (const tu of toolUses) {
        addTrace('TOOL', `→ <code>${tu.name}</code>(${JSON.stringify(tu.input)})`)
        await sleep(350)
        const result = simulateTool(tu.name!, tu.input as Record<string, string>)
        addTrace('TOOL', `← <code>${tu.name}</code>: ${result}`)
        toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: result })
      }

      messages.push({ role: 'assistant', content: data.content })
      messages.push({ role: 'user', content: toolResults })
      addTrace('STATE', `Iteration ${iterations} complete — updating state`)
      setActiveNode('agent')
      await sleep(100)
    }
  }

  async function runSupervisor(cfg: AgentConfig, userMessage: string) {
    const model = cfg.model
    const workerNames = cfg.supervisor?.workers ?? Object.keys(cfg.workers ?? {})
    const supervisorTools = configToAnthropicTools([
      ...workerNames.map(w => ({
        name: `delegate_to_${w}`,
        description: `Delegate a subtask to the ${w} agent`,
        params: ['task'],
      })),
      { name: 'finish', description: 'Signal completion with final synthesized answer', params: ['answer'] },
    ])

    addTrace('NODE', 'Supervisor initializing — decomposing task')
    setActiveNode('supervisor')

    const supervisorSystem = cfg.supervisor?.system_prompt ?? 'You are a supervisor. Delegate to workers then finish.'
    const messages: AnthropicMessage[] = [{
      role: 'user',
      content: `Task: ${userMessage}\n\nDecompose this task and delegate each subtask to the appropriate worker. Synthesize all results and call finish() when done.`,
    }]

    let rounds = 0
    while (rounds < (cfg.max_rounds ?? 6)) {
      if (abortRef.current?.signal.aborted) break
      rounds++
      const data = await claude(supervisorSystem, messages, supervisorTools, model)
      const toolUses = data.content.filter(b => b.type === 'tool_use')
      const texts = data.content.filter(b => b.type === 'text')

      if (texts.length) addTrace('ROUTER', `<strong>Supervisor:</strong> ${texts.map(b => b.text).join(' ')}`)

      if (!toolUses.length || data.stop_reason === 'end_turn') {
        addTrace('ANSWER', texts.map(b => b.text).join('\n') || 'All workers complete.', true)
        break
      }

      // Pre-check finish before delegation loop
      const finishCall = toolUses.find(tu => tu.name === 'finish')
      if (finishCall) {
        addTrace('ANSWER', finishCall.input?.answer ?? 'All tasks complete.', true)
        return
      }

      const toolResults: ContentBlock[] = []
      for (const tu of toolUses) {
        const workerName = tu.name!.replace('delegate_to_', '')
        addTrace('ROUTER', `Delegating to <code>${workerName}</code>: "${tu.input?.task}"`)
        setActiveNode(workerName)
        await sleep(400)

        const workerCfg = cfg.workers?.[workerName] ?? {}
        const workerData = await claude(
          workerCfg.system_prompt ?? `You are the ${workerName} specialist.`,
          [{ role: 'user', content: tu.input?.task ?? '' }],
          [],
          model,
        )
        const workerText = workerData.content.filter(b => b.type === 'text').map(b => b.text).join(' ')
        addTrace('WORKER', `<strong>${workerName}:</strong> ${workerText}`)
        toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: workerText })
        setActiveNode('supervisor')
      }

      messages.push({ role: 'assistant', content: data.content })
      messages.push({ role: 'user', content: toolResults })
      addTrace('STATE', `Round ${rounds} — results returned to supervisor`)
      await sleep(100)
    }
  }

  async function runParallel(cfg: AgentConfig, userMessage: string) {
    const tools = configToAnthropicTools(cfg.tools ?? [])
    const model = cfg.model

    addTrace('NODE', 'Fan-out node — dispatching all tools in parallel')
    setActiveNode('fan_out')

    const data = await claude(
      cfg.system_prompt,
      [{ role: 'user', content: userMessage + '\n\nCall ALL tools simultaneously in a single response.' }],
      tools,
      model,
    )

    const toolUses = data.content.filter(b => b.type === 'tool_use')
    const texts = data.content.filter(b => b.type === 'text')
    if (texts.length) addTrace('NODE', texts.map(b => b.text).join(' '))
    addTrace('PARALLEL', `Dispatching ${toolUses.length} tool calls in parallel`)

    const toolPromises = toolUses.map(async tu => {
      addTrace('TOOL', `[fan-out] <code>${tu.name}</code> ← ${JSON.stringify(tu.input)}`)
      await sleep(Math.random() * 500 + 200)
      const result = simulateTool(tu.name!, tu.input as Record<string, string>)
      addTrace('TOOL', `[done] <code>${tu.name}</code> → ${result}`)
      return { type: 'tool_result' as const, tool_use_id: tu.id, content: result }
    })

    const toolResults = await Promise.all(toolPromises)
    if (abortRef.current?.signal.aborted) return
    addTrace('NODE', 'All parallel tools complete — merging')
    setActiveNode('merge')

    const synthData = await claude(
      cfg.system_prompt,
      [
        { role: 'user', content: userMessage },
        { role: 'assistant', content: data.content },
        { role: 'user', content: toolResults },
      ],
      [],
      model,
    )

    setActiveNode('synthesize')
    const finalText = synthData.content.filter(b => b.type === 'text').map(b => b.text).join('\n')
    addTrace('ANSWER', finalText || 'Synthesis complete.', true)
  }

  async function runHITL(cfg: AgentConfig, userMessage: string, hitlEnabled: boolean) {
    const model = cfg.model
    const tools = cfg.tools ?? []
    const checkpointDefs = cfg.checkpoints ?? []
    const approvalTools = new Set(tools.filter(t => t.requires_approval).map(t => t.name))
    const cpFor = (trigger: string) =>
      checkpointDefs.find(c => c.after_node === trigger || c.before_tool === trigger)

    addTrace('NODE', 'Plan phase — creating execution plan')
    setActiveNode('plan')

    const planData = await claude(
      cfg.system_prompt + ' Start by creating a numbered execution plan.',
      [{ role: 'user', content: userMessage + '\n\nFirst, create a detailed numbered plan before executing any steps.' }],
      [],
      model,
    )
    const planText = planData.content.filter(b => b.type === 'text').map(b => b.text).join('\n')
    addTrace('HITL', `<strong>Execution Plan:</strong> ${planText}`)

    if (hitlEnabled) {
      const cp = cpFor('plan')
      const d = await requestCheckpoint(cp?.prompt ?? 'Agent has created an execution plan. Review above and approve to continue?')
      addTrace('HITL', `Checkpoint 1/${checkpointDefs.length || 3}: <strong>${d === 'approve' ? '✓ Approved' : '✗ Rejected'}</strong>`)
      if (d === 'reject') { addTrace('STATE', 'Execution halted at plan checkpoint.'); return }
    }

    let cpIndex = 1
    for (const tool of tools) {
      if (abortRef.current?.signal.aborted) break
      if (hitlEnabled && approvalTools.has(tool.name)) {
        const cp = cpFor(tool.name)
        cpIndex++
        const d = await requestCheckpoint(cp?.prompt ?? `Agent wants to execute <strong>${tool.name}</strong>. Approve?`)
        addTrace('HITL', `Checkpoint ${cpIndex}/${checkpointDefs.length || 3}: <strong>${d === 'approve' ? '✓ Approved' : '✗ Rejected'}</strong>`)
        if (d === 'reject') { addTrace('STATE', `Operation <code>${tool.name}</code> cancelled by user.`); return }
      }

      setActiveNode(toolNodeName(tool.name))
      await sleep(350)
      const result = simulateTool(tool.name, defaultArgsForTool(tool.params))
      addTrace('TOOL', `<code>${tool.name}</code> → ${result}`)
    }

    const completedTools = tools.map(t => t.name).join(', ')
    const finalData = await claude(
      cfg.system_prompt,
      [{ role: 'user', content: `Summarize what was accomplished for task: "${userMessage}". Tools executed: ${completedTools}. All human checkpoints approved.` }],
      [],
      model,
    )
    const finalText = finalData.content.filter(b => b.type === 'text').map(b => b.text).join('\n')
    addTrace('ANSWER', finalText || 'Pipeline complete — all steps executed with human approval.', true)
  }

  // ── main entry ────────────────────────────────────────────────────────────

  const run = useCallback(async (cfg: AgentConfig, userMessage: string, hitlEnabled: boolean) => {
    abortRef.current = new AbortController()
    startTimeRef.current = Date.now()
    tokenCountRef.current = 0

    setTraces([])
    setCheckpoints([])
    setRunState({ status: 'running', stepCount: 0, tokenCount: 0, elapsedMs: null, activeNode: null })

    try {
      if (cfg.pattern === 'react') await runReAct(cfg, userMessage)
      else if (cfg.pattern === 'supervisor') await runSupervisor(cfg, userMessage)
      else if (cfg.pattern === 'parallel') await runParallel(cfg, userMessage)
      else if (cfg.pattern === 'hitl') await runHITL(cfg, userMessage, hitlEnabled)
      else throw new Error(`Unknown pattern: "${cfg.pattern}"`)

      const elapsedMs = Date.now() - startTimeRef.current
      setRunState(prev => ({ ...prev, status: 'done', elapsedMs, activeNode: '__end__' }))
    } catch (e) {
      const isAbort = (e as Error).name === 'AbortError'
      setRunState(prev => ({
        ...prev,
        status: isAbort ? 'stopped' : 'error',
        elapsedMs: Date.now() - startTimeRef.current,
        activeNode: null,
      }))
      if (!isAbort) {
        setTraces(prev => [...prev, {
          id: uid(), tag: 'ERROR', tagClass: 'tag-error',
          content: `Runtime error: ${(e as Error).message}`,
          elapsed: ((Date.now() - startTimeRef.current) / 1000).toFixed(1) + 's',
        }])
      }
    } finally {
      abortRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const clearTraces = useCallback(() => {
    setTraces([])
    setCheckpoints([])
    setRunState({ status: 'idle', stepCount: 0, tokenCount: 0, elapsedMs: null, activeNode: null })
  }, [])

  return { traces, checkpoints, runState, run, stop, clearTraces, resolveCheckpoint }
}
