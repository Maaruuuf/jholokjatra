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
.\.venv\Scripts\Activate.ps1        
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
copy .env.example .env
```

## 2. API keys (both free, both optional)

| Provider | Get a key | Put in `.env` |
|---|---|---|
| Groq | https://console.groq.com/keys → Create API Key | `GROQ_API_KEY=gsk_...` |
.

## 3. First run

```bash
python -m scripts.smoke_test_apis      
pytest -q                               
uvicorn app.main:app --reload --port 8010 
$env:API_URL = "http://localhost:8010"        
streamlit run ui/app.py                
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


