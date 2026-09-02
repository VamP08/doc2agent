# Agent Eval Scorecard

**Score: 5/5** · models: `openai/gpt-oss-120b, qwen/qwen3.8-27b, openai/gpt-oss-20b` · 2026-09-02T04:19:23+00:00

Each task is verified against the live store, not the agent's claim.

| Task | Result | Time | Detail |
|---|---|---|---|
| count-warehouses (single read) | PASS | 1.0s | expected 4, reply: '4' |
| create-shipment (write + ID reporting) | PASS | 1.2s | SHP-1015: Delhi→Chennai 3.0kg |
| lookup-destination (targeted read) | PASS | 1.2s | reply: 'The shipment **SHP-1016** has its destination city set to **Jaipur**. (Retrieved' |
| multi-hop-courier (chained calls) | PASS | 13.5s | expected Meera, reply: 'The courier assigned to shipment **SHP-1017** is **Meera**. (Fetched via `GET /s' |
| status-update (write, store-verified) | PASS | 6.4s | events: [('created', 'Created by agent'), ('picked_up', 'collected by eval')] |
