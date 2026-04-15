import { useState, useEffect, useRef } from 'react'
import type { AgentConfig } from '../types'
import { PRESETS, DEFAULT_INPUTS } from '../lib/presets'
import { toolNodeName } from '../lib/api'

interface Props {
  onRun: (cfg: AgentConfig, userMessage: string, hitlEnabled: boolean) => void
  onStop: () => void
  isRunning: boolean
  activeNode: string | null
}

type Tab = 'config' | 'input' | 'graph'

export function LeftPanel({ onRun, onStop, isRunning, activeNode }: Props) {
  const [tab, setTab] = useState<Tab>('config')
  const [presetKey, setPresetKey] = useState('react')
  const [configText, setConfigText] = useState(JSON.stringify(PRESETS.react, null, 2))
  const [userMessage, setUserMessage] = useState(DEFAULT_INPUTS.react)
  const [hitlEnabled, setHitlEnabled] = useState(false)
  const [parsedCfg, setParsedCfg] = useState<AgentConfig>(PRESETS.react)
  const [configError, setConfigError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Parse config on edit (debounced)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      try {
        const cfg = JSON.parse(configText) as AgentConfig
        if (cfg.pattern) {
          setParsedCfg(cfg)
          setConfigError(null)
          if (cfg.hitl_enabled !== undefined) setHitlEnabled(!!cfg.hitl_enabled)
        }
      } catch {
        setConfigError('Invalid JSON')
      }
    }, 600)
  }, [configText])

  function loadPreset(key: string) {
    setPresetKey(key)
    const cfg = PRESETS[key]
    setConfigText(JSON.stringify(cfg, null, 2))
    setParsedCfg(cfg)
    setConfigError(null)
    setUserMessage(DEFAULT_INPUTS[key] ?? '')
    setHitlEnabled(!!cfg.hitl_enabled)
  }

  function handleRun() {
    if (!userMessage.trim()) { setTab('input'); return }
    onRun(parsedCfg, userMessage.trim(), hitlEnabled)
  }

  return (
    <div className="left-panel">
      {/* Tabs */}
      <div className="panel-tabs">
        {(['config', 'input', 'graph'] as Tab[]).map(t => (
          <div key={t} className={`tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {t.toUpperCase()}
          </div>
        ))}
      </div>

      {/* CONFIG TAB */}
      {tab === 'config' && (
        <div className="tab-content active">
          <div className="config-area">
            <textarea
              className={`config-editor${configError ? ' config-error' : ''}`}
              value={configText}
              onChange={e => setConfigText(e.target.value)}
              spellCheck={false}
            />
          </div>
          <div className="config-controls">
            <select
              className="preset-select"
              value={presetKey}
              onChange={e => loadPreset(e.target.value)}
            >
              {Object.entries(PRESETS).map(([key, cfg]) => (
                <option key={key} value={key}>{cfg.name}</option>
              ))}
            </select>
            <button
              className="btn btn-secondary"
              onClick={() => {
                if (configError) alert(`Config error: ${configError}`)
                else alert(`✓ Config valid — pattern: ${parsedCfg.pattern}, ${parsedCfg.tools?.length ?? 0} tools`)
              }}
            >
              Validate
            </button>
          </div>
        </div>
      )}

      {/* INPUT TAB */}
      {tab === 'input' && (
        <div className="tab-content active">
          <div className="input-area">
            <div className="input-label">User Message</div>
            <textarea
              className="user-input"
              value={userMessage}
              onChange={e => setUserMessage(e.target.value)}
              placeholder="Enter your task or question for the agent..."
            />
          </div>
          <div className="run-bar">
            <button
              className="btn btn-primary"
              id="runBtn"
              onClick={handleRun}
              disabled={isRunning}
            >
              {isRunning ? <><span className="spinner" />Running</> : '▶ Run Agent'}
            </button>
            {isRunning && (
              <button className="btn btn-stop" onClick={onStop}>■ Stop</button>
            )}
            <label className="hitl-toggle">
              <input
                type="checkbox"
                checked={hitlEnabled}
                onChange={e => setHitlEnabled(e.target.checked)}
              />
              {' '}HITL
            </label>
          </div>
        </div>
      )}

      {/* GRAPH TAB */}
      {tab === 'graph' && (
        <div className="tab-content active">
          <div className="graph-container">
            <GraphViz cfg={parsedCfg} activeNode={activeNode} />
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Graph Viz ─────────────────────────────────────────────────────────────

interface GraphVizProps {
  cfg: AgentConfig
  activeNode: string | null
}

function GraphViz({ cfg, activeNode }: GraphVizProps) {
  const COLOR: Record<string, string> = {
    react: 'var(--node-react)',
    supervisor: 'var(--node-supervisor)',
    parallel: 'var(--node-parallel)',
    hitl: 'var(--node-hitl)',
  }
  const c = COLOR[cfg.pattern] ?? 'var(--accent)'

  const nodes: Array<{ id: string; color: string; name: string; desc: string; pattern: string }> = []
  const edges: Array<{ label: string }> = []

  const pushNode = (id: string, color: string, name: string, desc: string, pattern: string) =>
    nodes.push({ id, color, name, desc, pattern })
  const pushEdge = (label: string) => edges.push({ label })

  pushNode('__start__', 'var(--text3)', '__start__', 'Graph entry point', 'state')
  pushEdge('→ initialize')

  if (cfg.pattern === 'react') {
    pushNode('agent', c, 'agent', 'Reason + select action', 'react')
    pushEdge('→ tool_call or finish')
    pushNode('tools', 'var(--accent2)', 'tools', cfg.tools?.map(t => t.name).join(', ') ?? '', 'parallel')
    pushEdge('→ observe → loop back')
    pushNode('agent2', c, 'agent', 'Update state, iterate or stop', 'react')
  } else if (cfg.pattern === 'supervisor') {
    pushNode('supervisor', c, 'supervisor', `Orchestrates: ${cfg.supervisor?.workers?.join(', ') ?? ''}`, 'supervisor')
    Object.keys(cfg.workers ?? {}).forEach(w => {
      pushEdge(`→ delegate → ${w}`)
      pushNode(w, 'var(--accent)', w, cfg.workers?.[w]?.tools?.join(', ') ?? 'no tools', 'react')
    })
    pushEdge('→ merge all results')
    pushNode('supervisor2', c, 'supervisor', 'Synthesize + DONE', 'supervisor')
  } else if (cfg.pattern === 'parallel') {
    pushNode('fan_out', c, 'fan_out', 'Dispatch tools simultaneously', 'parallel')
    cfg.tools?.forEach(t => pushEdge(`║ ${t.name}`))
    pushNode('merge', c, 'merge', `Strategy: ${cfg.merge_strategy ?? 'synthesize'}`, 'parallel')
    pushEdge('→ synthesize')
    pushNode('synthesize', c, 'synthesize', 'Combine into final response', 'parallel')
  } else if (cfg.pattern === 'hitl') {
    pushNode('plan', c, 'plan', 'Create execution plan', 'hitl')
    ;(cfg.tools ?? []).forEach(t => {
      pushEdge(t.requires_approval ? '⏸ CHECKPOINT' : '→')
      const nid = toolNodeName(t.name)
      pushNode(nid, c, nid, t.description ?? t.name, 'hitl')
    })
  }

  pushEdge('→ __end__')
  pushNode('__end__', 'var(--text3)', '__end__', 'Graph complete', 'state')

  // Interleave nodes and edges
  const items: Array<{ type: 'node'; node: typeof nodes[0] } | { type: 'edge'; edge: typeof edges[0] }> = []
  let ni = 0, ei = 0
  // start node first, then alternate edge→node
  items.push({ type: 'node', node: nodes[ni++] })
  while (ei < edges.length) {
    items.push({ type: 'edge', edge: edges[ei++] })
    if (ni < nodes.length) items.push({ type: 'node', node: nodes[ni++] })
  }

  return (
    <>
      {items.map((item, i) =>
        item.type === 'edge' ? (
          <div key={`e-${i}`} className="edge-line">{item.edge.label}</div>
        ) : (
          <div
            key={`n-${i}`}
            className={`graph-node ${item.node.pattern}${activeNode === item.node.id || activeNode === item.node.name ? ' active' : ''}`}
            id={`gnode-${item.node.id}`}
          >
            <div className="node-dot" style={{ background: item.node.color }} />
            <div className="node-info">
              <div className="node-name">{item.node.name}</div>
              <div className="node-desc">{item.node.desc}</div>
            </div>
          </div>
        )
      )}
    </>
  )
}
