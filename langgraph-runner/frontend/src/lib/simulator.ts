type ToolInput = Record<string, string>

type ToolHandler = (input: ToolInput) => string

const HANDLERS: Record<string, ToolHandler> = {
  web_search: i =>
    `Results for "${i.query}": [1] LangGraph 0.2 introduces native parallel tool execution with fan-out/fan-in patterns. [2] ReAct agents show 31% better performance on multi-step tasks vs chain-of-thought. [3] Anthropic releases extended thinking for complex reasoning chains.`,

  calculator: i => {
    try {
      const result = Function('"use strict"; return (' + i.expression + ')')()
      return `= ${result}`
    } catch (e) {
      return `Error: ${(e as Error).message}`
    }
  },

  summarize: () =>
    'Summary: Key concepts include iterative agent reasoning, stateful graph execution, and tool-augmented language models. Main takeaway: config-driven agents reduce boilerplate by 70%.',

  fetch_stock_price: i =>
    `${i.ticker}: $${(Math.random() * 400 + 100).toFixed(2)}, ${Math.random() > 0.5 ? '+' : '-'}${(Math.random() * 4).toFixed(2)}% today, Vol: ${(Math.random() * 50 + 10).toFixed(0)}M`,

  fetch_news: i =>
    `News for "${i.topic}": [1] Strong Q4 beat — revenue up 22% YoY. [2] New accelerator roadmap revealed at GTC 2025. [3] Analyst raises PT to $950, maintains Strong Buy.`,

  fetch_financials: i =>
    `${i.company} — Rev: $88.4B (+22% YoY) | Net Income: $29.8B | EPS: $11.93 | P/E: 42x | Mkt Cap: $2.2T | Gross Margin: 74.6%`,

  read_data: i =>
    `${i.source} — 847 total records. New this week: 142 users (fields: id, name, email, signup_date, plan). Status: 139 active, 3 pending verification.`,

  write_data: i =>
    `Write to ${i.target} — 142 records updated. Timestamps set. Audit log entry created. Duration: 0.34s.`,

  send_notification: i =>
    `Notification queued for ${i.recipient}. Template: "${(i.message ?? '').substring(0, 60)}...". Estimated delivery: <2min. Expected open rate: 68%.`,

  code_exec: () =>
    'Execution OK. weather_fetch(city: str) -> dict defined with httpx client, retry logic, API key via env var, typed returns. Tests: 3/3 passed.',

  delegate_to_researcher: i =>
    `Research complete: ${i.task}. Found 4 relevant sources. Key facts extracted and validated.`,

  delegate_to_coder: i =>
    `Code complete: ${i.task}. Function implemented with type hints, docstring, error handling, and unit tests.`,

  delegate_to_writer: i =>
    `Writing complete: ${i.task}. 400-word technical blog post drafted with intro, code walkthrough, and conclusion.`,

  finish: i => i.answer ?? 'All tasks complete.',
}

export function simulateTool(name: string, input: ToolInput): string {
  const handler = HANDLERS[name]
  return handler ? handler(input) : `${name}: OK`
}

// Default args to use when running HITL tools derived from config params
const PARAM_DEFAULTS: Record<string, string> = {
  source: 'customer_database',
  target: 'users_table',
  content: 'batch_update',
  recipient: 'new_users',
  message: 'Welcome to the platform! Your account is ready.',
}

export function defaultArgsForTool(params: string[]): ToolInput {
  return Object.fromEntries(params.map(p => [p, PARAM_DEFAULTS[p] ?? p]))
}
