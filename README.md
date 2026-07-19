# doc2agent

Point it at a REST API's documentation and it builds a working AI agent for that API on the spot. The agent makes real HTTP calls, shows every request it makes, and asks before it writes anything.

Live demo: **[doc2agent.onrender.com](https://doc2agent.onrender.com)** (free hosting, so the first load after idle takes about a minute). There's a built-in demo API to try it against, and a dashboard at [/monitor](https://doc2agent.onrender.com/monitor) where you can watch the agent's calls land in real time.

## What it does

Most tool-calling demos ship with tools someone wrote by hand. Here the tools don't exist until runtime:

1. Give it a docs URL. If the URL serves an OpenAPI/Swagger spec, it's parsed directly with no LLM involved. If it's an HTML docs page, the text gets scraped and an LLM extracts the endpoints into a strict schema (validated, invalid entries dropped).
2. Each endpoint becomes a tool-calling schema and a chat agent gets wired to them.
3. Ask a question. The agent chains real HTTP calls, retries on errors, and every request appears in the UI with its status code.

Beyond the core loop:

- Write operations (POST/PUT/PATCH/DELETE) pause the agent and ask for your approval before executing. There's an auto-approve toggle if you'd rather not click.
- Tool calls stream to the UI over SSE as they happen, including routing decisions and approval prompts.
- Large APIs get routed: endpoints are clustered by path segment and a small model picks the relevant clusters per question, so a 200-endpoint API doesn't blow the context budget.
- Sessions persist in SQLite, so conversations survive restarts.
- Any ingested API can be exported as a standalone MCP server file, usable from Claude Desktop or Cursor.
- SSRF protection: every hostname must resolve to a public IP or the request is refused.

Component-level detail lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The built-in demo

The app ships with AeroTrack, a simulated logistics API (shipments, couriers, warehouses) with a background simulator that keeps orders flowing. Its OpenAPI spec is auto-generated, so it doubles as the test case for the deterministic ingestion path. Swagger docs are at `/demo/docs`.

The demo worth doing: open `/monitor` in one window and the app in another, click "Use the built-in AeroTrack demo API", then ask:

> Create a new express shipment of 5 kg from Mumbai to Pune, find an idle courier, and assign them to it.

You'll get an approval prompt for each write, and the monitor shows the agent's requests landing against the simulator's background traffic, with the new shipment appearing in the table.

## Running locally

```bash
git clone https://github.com/VamP08/doc2agent && cd doc2agent
conda create -n doc2agent python=3.12 -y
conda activate doc2agent
pip install -r requirements.txt
cp .env.example .env    # put a free key from console.groq.com in here
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Public APIs that work well:

| URL | Ask |
|---|---|
| `https://petstore3.swagger.io/api/v3/openapi.json` | "Find the available pets and summarise them" |
| `https://api.weather.gov/openapi.json` | "What's the forecast for latitude 39.74, longitude -104.99?" |

Note: docs sites that render via JavaScript can't be scraped. Use the API's spec URL instead (often at `/openapi.json`).

## Tests and evals

```bash
pytest evals -q               # 30 offline tests, no API key needed
python -m evals.agent_evals   # live tasks against a running server
```

The offline suite covers spec parsing against a pinned Petstore snapshot, the SSRF guard, the demo API contracts, tool synthesis, MCP export validity, and session serialization. The live evals run scripted tasks and verify the outcome against the actual data store rather than trusting the agent's reply; results go to `evals/scorecard.md`. CI runs the offline suite on every push, and the live evals too if a `GROQ_API_KEY` secret is configured.

## Deploying

The Dockerfile listens on `$PORT` if the host sets it, otherwise 7860. Currently running on Render's free tier: connect the repo, pick the Docker runtime, set `GROQ_API_KEY` in the environment, done. Sessions and demo data are demo-scale by design and reset on redeploy.

## Stack

FastAPI, Groq (Llama 3.3 70B), httpx, BeautifulSoup, Pydantic, SQLite, vanilla JS. No frontend framework. MIT licensed.
