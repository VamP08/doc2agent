# Agent Eval Scorecard

**Score: 5/5** · models: `openai/gpt-oss-120b, qwen/qwen3.8-27b, openai/gpt-oss-20b` · 2026-09-02T08:31:38+00:00

Each task is verified against the live store, not the agent's claim.

| Task | Result | Time | Detail |
|---|---|---|---|
| count-warehouses (single read) | PASS | 1.1s | expected 4, reply: '4' |
| create-shipment (write + ID reporting) | PASS | 1.3s | SHP-1023: Delhi→Chennai 3.0kg |
| lookup-destination (targeted read) | PASS | 1.1s | reply: 'The shipment **SHP-1024** has its destination city set to **Jaipur**. (Data retr' |
| multi-hop-courier (chained calls) | PASS | 27.1s | expected Arjun, reply: 'The courier assigned to shipment **SHP-1026** is **Arjun** (courier ID\u202fCR‑1). Th' |
| status-update (write, store-verified) | PASS | 5.8s | events: [('created', 'Created by agent'), ('picked_up', 'collected by eval')] |
