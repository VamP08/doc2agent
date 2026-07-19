# Agent Eval Scorecard

**Score: 5/5** · model: `llama-3.3-70b-versatile` · 2026-07-19T12:12:00+00:00

Each task is verified against the live store, not the agent's claim.

| Task | Result | Time | Detail |
|---|---|---|---|
| count-warehouses (single read) | PASS | 1.1s | expected 4, reply: '4' |
| create-shipment (write + ID reporting) | PASS | 1.2s | SHP-1011: Delhi→Chennai 3.0kg |
| lookup-destination (targeted read) | PASS | 1.0s | reply: 'The destination city of shipment SHP-1012 is Jaipur.' |
| multi-hop-courier (chained calls) | PASS | 21.4s | expected Arjun, reply: 'The name of the courier assigned to shipment SHP-1013 is Arjun.' |
| status-update (write, store-verified) | PASS | 18.6s | events: [('created', 'Created by agent'), ('picked_up', 'collected by eval')] |
