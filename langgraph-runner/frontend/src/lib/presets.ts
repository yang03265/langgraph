import type { AgentConfig } from '../types'

export const PRESETS: Record<string, AgentConfig> = {
  react: {
    pattern: 'react',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Research ReAct Agent',
    description: 'A ReAct agent that iteratively reasons and calls tools to answer questions.',
    tools: [
      { name: 'web_search', description: 'Search the web for current information', params: ['query'] },
      { name: 'calculator', description: 'Evaluate mathematical expressions', params: ['expression'] },
      { name: 'summarize', description: 'Summarize a long text passage', params: ['text'] },
    ],
    system_prompt:
      'You are a research assistant. Use your tools iteratively to answer questions thoroughly. Always reason step-by-step before calling a tool. After using tools, synthesize the results into a comprehensive answer.',
    max_iterations: 5,
    stop_condition: 'task_complete',
  },

  supervisor: {
    pattern: 'supervisor',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Supervisor + Worker Agents',
    description: 'A supervisor LLM routes subtasks to specialized worker agents.',
    system_prompt: '',
    supervisor: {
      system_prompt:
        'You are an orchestrator. Analyze the task and delegate to workers: researcher, coder, or writer. Use delegate_to_researcher, delegate_to_coder, or delegate_to_writer tools. When all work is done, call finish() with the final synthesized answer.',
      workers: ['researcher', 'coder', 'writer'],
    },
    workers: {
      researcher: {
        system_prompt: 'You are a research specialist. Find facts, synthesize information, and return a concise summary of your findings.',
        tools: ['web_search'],
      },
      coder: {
        system_prompt: 'You are a coding specialist. Write clean, well-commented, production-ready code. Include error handling and type hints.',
        tools: ['code_exec'],
      },
      writer: {
        system_prompt: 'You are a writing specialist. Craft clear, engaging, well-structured content tailored for a technical audience.',
        tools: [],
      },
    },
    max_rounds: 6,
  },

  parallel: {
    pattern: 'parallel',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Parallel Tool Execution',
    description: 'Dispatch multiple tool calls simultaneously and synthesize results.',
    tools: [
      { name: 'fetch_stock_price', description: 'Get current stock price for a ticker symbol', params: ['ticker'] },
      { name: 'fetch_news', description: 'Get recent news headlines for a topic', params: ['topic'] },
      { name: 'fetch_financials', description: 'Get company financial summary and key metrics', params: ['company'] },
    ],
    parallel_fan_out: true,
    merge_strategy: 'synthesize',
    system_prompt:
      'You are a financial analyst. Fan out ALL available tool calls in parallel simultaneously, then synthesize a comprehensive investment brief from the combined results.',
  },

  hitl: {
    pattern: 'hitl',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    hitl_enabled: true,
    name: 'Human-in-the-Loop Agent',
    description: 'Agent pauses at critical decision points to request human approval before proceeding.',
    tools: [
      { name: 'read_data', description: 'Read records from a data source', params: ['source'] },
      { name: 'write_data', description: 'Write or modify data — requires human approval', params: ['target', 'content'], requires_approval: true },
      { name: 'send_notification', description: 'Send alert or notification — requires human approval', params: ['recipient', 'message'], requires_approval: true },
    ],
    checkpoints: [
      { after_node: 'plan', prompt: 'Agent has created an execution plan. Approve to proceed?' },
      { before_tool: 'write_data', prompt: 'Agent wants to write data. Review and approve?' },
      { before_tool: 'send_notification', prompt: 'Agent wants to send notifications. Approve?' },
    ],
    system_prompt:
      'You are a data pipeline agent. First create a detailed plan, then read data, then request approval before any write or notification operations. Be explicit about what you intend to do at each step.',
  },

  'react-code': {
    pattern: 'react',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Code Debugging Assistant',
    description: 'A ReAct agent that debugs code, searches for solutions, and writes fixes.',
    system_prompt:
      'You are a code debugging specialist. Analyze code problems, search for solutions online, and execute code to test fixes. Always think through the issue step-by-step before writing code. After implementing a fix, verify it works correctly.',
    max_iterations: 8,
    stop_condition: 'task_complete',
    tools: [
      { name: 'code_exec', description: 'Execute Python code and see the output or error messages', params: ['code'] },
      { name: 'web_search', description: 'Search the web for documentation, Stack Overflow answers, or error solutions', params: ['query'] },
      { name: 'write_data', description: 'Write the corrected code to a file', params: ['target', 'content'] },
    ],
  },

  'react-simple': {
    pattern: 'react',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Quick Calculator Assistant',
    description: 'A minimal ReAct agent with a single tool—useful as a template.',
    system_prompt: 'You are a quick calculator. When asked a math problem, use the calculator tool to solve it. Be concise in your responses.',
    max_iterations: 2,
    stop_condition: 'task_complete',
    tools: [{ name: 'calculator', description: 'Evaluate mathematical expressions and return numeric results', params: ['expression'] }],
  },

  'supervisor-product': {
    pattern: 'supervisor',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Product Development Team',
    description: 'A supervisor coordinates a product team with analyst, designer, developer, and QA specialists.',
    system_prompt: '',
    supervisor: {
      system_prompt:
        'You are a product manager. Analyze the request and delegate tasks to specialists: analyst, designer, developer, or qa. Use delegate_to_analyst, delegate_to_designer, delegate_to_developer, or delegate_to_qa tools. Coordinate their work and synthesize the final result using finish().',
      workers: ['analyst', 'designer', 'developer', 'qa'],
    },
    workers: {
      analyst: {
        system_prompt:
          'You are a product analyst. Research market trends, user needs, and competitive landscape. Provide actionable insights and recommendations.',
        tools: ['web_search'],
      },
      designer: {
        system_prompt: 'You are a product designer. Design user interfaces and experiences. Consider usability, accessibility, and aesthetic appeal. Provide wireframes and design specs.',
        tools: [],
      },
      developer: {
        system_prompt:
          'You are a software developer. Write clean, maintainable code following best practices. Implement features efficiently and consider performance implications.',
        tools: ['code_exec'],
      },
      qa: {
        system_prompt: 'You are a QA specialist. Create test plans, identify edge cases, and validate that features work correctly across different scenarios.',
        tools: [],
      },
    },
    max_rounds: 8,
  },

  'parallel-research': {
    pattern: 'parallel',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    name: 'Multi-Source Research Aggregator',
    description: 'Gather information from multiple research sources in parallel and synthesize comprehensive insights.',
    system_prompt:
      'You are a research aggregator. Simultaneously search the web, fetch news headlines, and summarize findings to provide a comprehensive overview of a topic. Fan out all available tools in parallel, then synthesize the results into a clear, well-structured report.',
    tools: [
      { name: 'web_search', description: 'Search the web for articles and detailed information on a topic', params: ['query'] },
      { name: 'fetch_news', description: 'Get recent news headlines and breaking news on a topic', params: ['topic'] },
      { name: 'summarize', description: 'Summarize long-form content into key points', params: ['text'] },
    ],
    parallel_fan_out: true,
    merge_strategy: 'synthesize',
  },

  'hitl-deploy': {
    pattern: 'hitl',
    model: 'mistralai/devstral-2-123b-instruct-2512',
    hitl_enabled: true,
    name: 'Deployment Pipeline with Approval Gates',
    description: 'Deploy code changes through approval gates: plan, code review, and deployment notification.',
    system_prompt:
      'You are a deployment orchestrator. Create a detailed deployment plan first, then execute code changes and send deployment notifications. Always be explicit about what you intend to do at each step. Request human approval before executing sensitive operations.',
    tools: [
      { name: 'code_exec', description: 'Execute deployment scripts or run tests—no approval required', params: ['code'] },
      { name: 'write_data', description: 'Write code or configuration changes—requires human approval', params: ['target', 'content'], requires_approval: true },
      { name: 'send_notification', description: 'Send deployment notifications to team—requires human approval', params: ['recipient', 'message'], requires_approval: true },
    ],
    checkpoints: [
      { after_node: 'plan', prompt: 'Agent has created a deployment plan. Review and approve to proceed?' },
      { before_tool: 'write_data', prompt: 'Agent wants to write code/config changes. Review the changes and approve?' },
      { before_tool: 'send_notification', prompt: 'Agent wants to notify the team of deployment. Approve?' },
    ],
  },
}

export const DEFAULT_INPUTS: Record<string, string> = {
  react: 'What are the latest developments in LangGraph multi-agent systems, and what is 2^10 + 137?',
  supervisor: 'Build a Python function that fetches weather data from an API, then write a blog post explaining how it works for developers.',
  parallel: 'Give me a full investment brief on NVDA — stock price, recent news, and key financials.',
  hitl: 'Read our customer database and send a personalized welcome notification to all new users from this week.',
  'react-code': 'Debug this Python code: def factorial(n):\\n  return n * factorial(n-1). Find the issue and provide a fixed version.',
  'react-simple': 'What is the square root of 144, and what is 256 divided by 8?',
  'supervisor-product': 'Design a mobile app for task management. Analyze the market, design the UI/UX, outline the tech stack, and plan testing.',
  'parallel-research': 'Research recent advances in AI safety and provide a comprehensive overview from multiple sources.',
  'hitl-deploy': 'Deploy version 2.1.0 of our API service with a schema migration and notify the DevOps team.',
}
