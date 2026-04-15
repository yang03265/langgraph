# Contributing to LangGraph Runner

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/your-username/langgraph-runner.git
   cd langgraph-runner
   ```
3. **Set up the development environment** following the [Quickstart](README.md#quickstart) section in the README

## Development Workflow

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Running tests:**
```bash
pytest ../tests/test_backend.py -v
```

**Starting the dev server:**
```bash
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

**Running tests:**
```bash
npm test
```

**Building for production:**
```bash
npm run build
```

## Before Submitting a PR

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Write or update tests** for your changes
3. **Ensure tests pass:**
   - Backend: `cd backend && pytest ../tests/test_backend.py -v`
   - Frontend: `cd frontend && npm test`
4. **Check code quality:**
   - Backend: Verify no import errors `python -m py_compile main.py`
   - Frontend: Type checking is part of build (`npm run build`)
5. **Commit with clear messages:**
   ```bash
   git commit -m "brief description of changes"
   ```
6. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

## Submitting a Pull Request

1. Open a PR against the `main` branch
2. Provide a clear description of:
   - What problem does this solve?
   - How does it work?
   - Are there any breaking changes?
3. Link any relevant issues (e.g., "Closes #123")
4. Ensure all CI checks pass

## Project Structure

- **`backend/`** — FastAPI server that proxies requests to NVIDIA's OpenAI-compatible API
- **`frontend/`** — React + TypeScript UI built with Vite
- **`configs/`** — Example JSON configuration files for different agent patterns
- **`tests/`** — Backend test suite

## Key Concepts

- **Patterns**: ReAct, Supervisor/Workers, Parallel, and Human-in-the-Loop
- **Config-driven**: Agents are defined entirely in JSON with no code changes
- **Tool Simulation**: Tools return mock responses; connect real APIs by modifying `simulator.ts`
- **HITL**: Human checkpoints pause execution for approval before sensitive operations

## Areas for Contribution

### High Priority
- [ ] Support for additional LLM providers (Anthropic, Gemini, etc.)
- [ ] Real tool implementations (replace `simulator.ts` mocks)
- [ ] Docker support for easier deployment
- [ ] GitHub Actions CI/CD pipeline

### Medium Priority
- [ ] Additional agent patterns
- [ ] Enhanced error handling and retry logic
- [ ] Configuration validation improvements
- [ ] Performance optimizations

### Low Priority
- [ ] UI/UX improvements
- [ ] Documentation enhancements
- [ ] Additional example configs

## Code Style

- **Backend**: Follow PEP 8 conventions. Use type hints.
- **Frontend**: Follow the existing TypeScript/React patterns. Use strict mode.
- **Comments**: Keep comments focused on "why", not "what" — code should be self-documenting

## Questions or Issues?

- Open an issue on GitHub for bugs and feature requests
- Discussions are welcome in PR comments

## License

By contributing, you agree that your contributions will be licensed under the same MIT License as the project.

Happy coding! 🚀
