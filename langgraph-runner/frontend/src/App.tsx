import { useAgentRunner } from './hooks/useAgentRunner'
import { LeftPanel } from './components/LeftPanel'
import { TraceStream } from './components/TraceStream'
import type { AgentConfig } from './types'

export default function App() {
  const { traces, checkpoints, runState, run, stop, clearTraces, resolveCheckpoint } = useAgentRunner()

  const isRunning = runState.status === 'running'

  const statusLabel = () => {
    switch (runState.status) {
      case 'running': return runState.activeNode ? `RUNNING — ${runState.activeNode}` : 'RUNNING'
      case 'done': return 'COMPLETE'
      case 'error': return 'ERROR'
      case 'stopped': return 'STOPPED'
      default: return 'EXECUTION TRACE'
    }
  }

  const elapsedLabel = runState.elapsedMs != null
    ? `${(runState.elapsedMs / 1000).toFixed(1)}s`
    : '—'

  function handleRun(cfg: AgentConfig, userMessage: string, hitlEnabled: boolean) {
    run(cfg, userMessage, hitlEnabled)
  }

  return (
    <>
      {/* Header */}
      <div className="header">
        <div className="logo">
          <div className="logo-icon">LG</div>
          <div className="logo-name">Lang<span>Graph</span> Runner</div>
        </div>
        <div className="header-badges">
          <span className="badge badge-react">ReAct</span>
          <span className="badge badge-supervisor">Supervisor</span>
          <span className="badge badge-parallel">Parallel</span>
          <span className="badge badge-hitl">HITL</span>
        </div>
      </div>

      {/* Main layout */}
      <div className="main">
        <LeftPanel
          onRun={handleRun}
          onStop={stop}
          isRunning={isRunning}
          activeNode={runState.activeNode}
        />

        {/* Right panel */}
        <div className="right-panel">
          <div className="exec-header">
            <div className="exec-title">
              <div className={`status-dot${isRunning ? ' running' : runState.status === 'done' ? ' done' : runState.status === 'error' ? ' error' : ''}`} />
              <span>{statusLabel()}</span>
            </div>
            <div className="exec-meta">
              <div className="meta-item">STEPS <span className="meta-val">{runState.stepCount}</span></div>
              <div className="meta-item">TOKENS <span className="meta-val">{runState.tokenCount > 0 ? runState.tokenCount.toLocaleString() : '—'}</span></div>
              {isRunning && (
                <button className="btn btn-stop" id="stopBtnHeader" onClick={stop}>■ Stop</button>
              )}
              <button className="btn btn-secondary" style={{ padding: '3px 8px', fontSize: 10 }} onClick={clearTraces}>
                Clear
              </button>
            </div>
          </div>

          <TraceStream
            traces={traces}
            checkpoints={checkpoints}
            onResolveCheckpoint={resolveCheckpoint}
          />

          <div className="status-bar">
            <span>Model: <span className="highlight" id="modelLabel">gemini-2.0-flash</span></span>
            <span id="patternLabel">Elapsed: <span className="highlight">{elapsedLabel}</span></span>
          </div>
        </div>
      </div>
    </>
  )
}
