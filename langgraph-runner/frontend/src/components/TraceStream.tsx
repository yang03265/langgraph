import { useEffect, useRef } from 'react'
import type { TraceEvent, HITLCheckpointEvent } from '../types'

interface Props {
  traces: TraceEvent[]
  checkpoints: HITLCheckpointEvent[]
  onResolveCheckpoint: (id: string, decision: 'approve' | 'reject') => void
}

export function TraceStream({ traces, checkpoints, onResolveCheckpoint }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [traces, checkpoints])

  if (traces.length === 0 && checkpoints.length === 0) {
    return (
      <div className="trace-stream">
        <div className="empty-state">
          <div className="empty-icon">◈</div>
          <div className="empty-text">
            Select a config preset and enter a task.<br />
            The agent execution trace will stream here.
          </div>
          <div className="empty-hint">← Start with CONFIG tab, then INPUT</div>
        </div>
      </div>
    )
  }

  // Merge traces + unresolved checkpoints into a single ordered stream
  // Checkpoints are rendered inline after the trace event that triggered them
  return (
    <div className="trace-stream">
      {traces.map(event => (
        <TraceRow key={event.id} event={event} />
      ))}
      {checkpoints
        .filter(cp => !cp.resolved)
        .map(cp => (
          <HITLCheckpoint key={cp.id} checkpoint={cp} onResolve={onResolveCheckpoint} />
        ))}
      {checkpoints
        .filter(cp => cp.resolved)
        .map(cp => (
          <ResolvedCheckpoint key={cp.id} checkpoint={cp} />
        ))}
      <div ref={bottomRef} />
    </div>
  )
}

// ─── Individual trace row ──────────────────────────────────────────────────

function TraceRow({ event }: { event: TraceEvent }) {
  return (
    <div className="trace-event">
      <div className="trace-ts">{event.elapsed}</div>
      <div className={`trace-tag ${event.tagClass}`}>{event.tag}</div>
      <div
        className={`trace-content${event.isAnswer ? ' answer' : ''}`}
        dangerouslySetInnerHTML={{ __html: event.content }}
      />
    </div>
  )
}

// ─── Active HITL checkpoint (awaiting decision) ────────────────────────────

function HITLCheckpoint({
  checkpoint,
  onResolve,
}: {
  checkpoint: HITLCheckpointEvent
  onResolve: (id: string, decision: 'approve' | 'reject') => void
}) {
  return (
    <div className="hitl-checkpoint">
      <div className="hitl-title">⏸ HUMAN CHECKPOINT</div>
      <div
        className="hitl-question"
        dangerouslySetInnerHTML={{ __html: checkpoint.question }}
      />
      <div className="hitl-btns">
        <button
          className="hitl-btn hitl-approve"
          onClick={() => onResolve(checkpoint.id, 'approve')}
        >
          ✓ Approve
        </button>
        <button
          className="hitl-btn hitl-reject"
          onClick={() => onResolve(checkpoint.id, 'reject')}
        >
          ✗ Reject
        </button>
      </div>
    </div>
  )
}

// ─── Resolved checkpoint (dimmed, shows outcome) ───────────────────────────

function ResolvedCheckpoint({ checkpoint }: { checkpoint: HITLCheckpointEvent }) {
  const approved = checkpoint.decision === 'approve'
  return (
    <div className="hitl-checkpoint resolved">
      <div className="hitl-title">⏸ HUMAN CHECKPOINT</div>
      <div
        className="hitl-question"
        dangerouslySetInnerHTML={{ __html: checkpoint.question }}
        style={{ opacity: 0.5 }}
      />
      <div className="hitl-btns">
        <span
          style={{
            fontFamily: 'IBM Plex Mono, monospace',
            fontSize: 11,
            color: approved ? 'var(--accent)' : 'var(--red)',
          }}
        >
          {approved ? '✓ Approved — continuing execution' : '✗ Rejected — execution halted'}
        </span>
      </div>
    </div>
  )
}
