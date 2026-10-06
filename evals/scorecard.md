# Agent Eval Scorecard

**Score: 4/4** · models: `openai/gpt-oss-120b, qwen/qwen3.8-27b, openai/gpt-oss-20b` · 2026-10-06T19:27:39+00:00

Each task is verified against the live store, not the agent's claim.

| Task | Result | Time | Detail |
|---|---|---|---|
| count-warehouses (single read) | PASS | 1.7s | expected 4, reply: '4' |
| create-shipment (write + ID reporting) | PASS | 1.6s | SHP-1011: Delhi→Chennai 3.0kg |
| lookup-destination (targeted read) | PASS | 1.1s | reply: 'The shipment **SHP-1012** has its destination city set to **Jaipur**. (Retrieved' |
| multi-hop-courier (chained calls) | SKIP | 0.0s | skipped — no idle courier available |
| status-update (write, store-verified) | PASS | 13.5s | events: [('created', 'Created by agent'), ('picked_up', 'collected by eval')] |
