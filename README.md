# JholokJatra (ঝলকযাত্রা)

An agentic "best day to go" advisor for Bangladesh trips. Pick a destination and a date range; agents pull live
data from **free public APIs** and return a go / caution / avoid verdict per day, where **every reason links to the
raw API response** behind it.

Destinations: Cox's Bazar, Saint Martin's Island, Kuakata, Sundarbans (Karamjal), Ratargul, Sajek, Bandarban, Sreemangal
(coordinates are approximate points of interest).

## 1. One-time setup

Python 3.11+ required.

**Windows (PowerShell)**
```powershell
cd jholokjatra
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
copy .env.example .env
```

**WSL / Linux / macOS**
```bash
cd jholokjatra
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
```

Optional extras: `pip install -r requirements-ui.txt` (Streamlit + maps). ChromaDB is off by default (`USE_CHROMA=false`) because it downloads an ~80 MB embedding model on first use; tips use SQLite keyword search instead.

## 2. API keys (both free, both optional)

The app works with **no keys** (deterministic template narrative). Keys only upgrade the narrative and free-text parsing.

| Provider | Get a key | Put in `.env` |
|---|---|---|
| Groq | https://console.groq.com/keys → Create API Key | `GROQ_API_KEY=gsk_...` |
| Gemini | https://aistudio.google.com/apikey → Create API key | `GEMINI_API_KEY=...` |

Rules: never commit `.env` (it is in `.gitignore`), no quotes or spaces around the value, restart the server after editing.
Check them: `python -m scripts.check_keys`.
Default Groq models are `openai/gpt-oss-20b` (small tier) and `openai/gpt-oss-120b` (large tier). These are reasoning models, so the code gives them extra token headroom and sets `GROQ_REASONING_EFFORT=low`. Model names change; if a call returns 404, update `GROQ_MODEL_*` in `.env` from Groq's model list.

Groq-only setup: `LLM_PROVIDER_ORDER=groq` (the default in `.env.example`).

Optional local model: install Ollama, `ollama pull qwen2.5:7b`, set `OLLAMA_ENABLED=true`.

## 3. First run

```bash
python -m scripts.smoke_test_apis      # confirms every public API is reachable from your network
pytest -q                              # 33 offline tests (mocked internet, no keys needed)
uvicorn app.main:app --reload --port 8010 
$env:API_URL = "http://localhost:8010"        # API docs at http://localhost:8000/docs
streamlit run ui/app.py                # UI at http://localhost:8501
```

Try it:
```bash
curl -X POST localhost:8010/plan -H "content-type: application/json" -d '{"destination":"saint_martin"}'
curl -X POST localhost:8010/plan -H "content-type: application/json" -d '{"query":"কক্সবাজার next 5 days","language":"bn"}'
```

## 4. Public APIs used

Open-Meteo (forecast, marine waves, GloFAS flood, archive), GDACS (cyclone/flood alerts), USGS (earthquakes),
OpenStreetMap Overpass (hospitals etc.), Wikivoyage (tips, CC BY-SA). All free; none needs a key.

## 5. Roadmap stage → code

| Stage | Where |
|---|---|
| 1 Async/FastAPI | `app/http.py` (retries, backoff, cache, stale-if-error), `app/data.py` (parallel fetch), `/plan/stream` (SSE) |
| 2 LLM fundamentals | `app/llm/router.py` (small/large tiers, provider fallback), `budget.py` (token cap), rules-first `parser.py` |
| 3 Tool calling | `app/tools/registry.py` (Pydantic args, JSON schemas, recoverable errors), `llm/structured.py` (validate + retry) |
| 4 Memory | `memory/prefs.py` (cross-session), `memory/tips.py` (Wikivoyage + optional Chroma) |
| 5 Single agent | `agents/react.py` (ReAct, iteration cap, graceful degradation) |
| 6 Multi-agent | `agents/graph.py`, `nodes.py` (LangGraph: weather, safety, logistics, guide, supervisor with safety veto) |
| 7 Human-in-the-loop | `pipeline.py` approval gate, `POST /plans/{id}/decision`, `GET /plans/{id}/audit` |
| 8 Evaluation | `tests/`, `evals/backtest.py` (past events), `verify.py` (every narrative number must match evidence) |
| 9 Observability | `tracing.py` spans + `GET /metrics` (latency, tokens, errors) |
| 10 Security | `security/sanitize.py`, untrusted text never enters the planning prompt, PII redaction |
| 11 Deployment | `Dockerfile`, `docker-compose.yml`, `deploy/k8s/`, `.github/workflows/` |
| 12 Portfolio | `ui/app.py`, this README, backtest report |

## 6. Design rules

- **Evidence-cited**: each reason carries a `ref`; `GET /evidence/{ref}` returns the stored raw response.
- **Deterministic core**: verdicts come from `scoring.py`, not from an LLM. The LLM only writes the summary, and its numbers are verified.
- **Safety veto**: if the safety agent says avoid and weather says go, the final verdict is avoid, and the conflict is reported.
- **Never silently risky**: if no day is a clear "go", the plan pauses for your approval.

## 7. Honest limitations

- Thresholds in `scoring.py` are heuristic comfort/safety rules, **not official warnings**. Follow BMD and local authorities.
- Flood score is a heuristic on GloFAS discharge (rise vs. the window minimum), not a calibrated flood forecast.
- Marine forecast covers about 7 days; sea trips beyond that are capped at "caution".
- GDACS response parsing is defensive but unverified against live data from this build; run the smoke test.
- `evals/fixtures/events.json` expectations are from memory of real events; verify and edit them. The backtest scores observed conditions, not forecast skill.
- Single-process SQLite cache: fine for a demo; use Postgres/Redis before running multiple replicas.

## 8. Next ideas

Aladhan prayer times, sunrise/sunset for photo timing, Frankfurter currency for foreign visitors, Eid/hartal calendar,
Phoenix/Langfuse OpenTelemetry export, a `/compare` endpoint ranking destinations for the same dates.
