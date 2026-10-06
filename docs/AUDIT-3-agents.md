# 3-Independent-Agent Audit — browser-agent outcome & side-effect verifier
_Run 2026-10-02. Three adversarial agents, independent lenses, triangulated._

> **Historical record — superseded on go-to-market.** The "do not build as a paid product / require written WTP first" recommendation below reflects this audit's point-in-time view. The current plan is to **launch the OSS engine directly to market** with no willingness-to-pay gate; commercial (P3) features are demand-driven (FEATURE-SPEC §17). The audit's *technical* findings (the wedge, the failure modes, the determinism angle, the state-reset risk) still stand.

## Triangulated verdict
- **As a paid product:** DO NOT BUILD (unproven WTP + no defensible wedge + frameworks self-shipping the fix + name taken + tiny buyer pool).
- **The survivor across all 3 lenses:** a PUBLIC BENCHMARK of browser-agent false-completion + forbidden-side-effect rates on backend ground truth.
- (User has since decided to build the product anyway; this audit stands as the risk record.)

| Agent | Lens | Verdict |
|---|---|---|
| 1 | Demand / willingness-to-pay | PLAUSIBLE BUT UNPROVEN |
| 2 | Competition / platform absorption | OCCUPIED BUT WINNABLE AT SMALL SCALE |
| 3 | Kill-it / solo feasibility | BUILD ONLY AS ≤2-WK EXPERIMENT; lean KILL on revenue |

---

## Agent 1 — Demand & Willingness-to-Pay → PLAUSIBLE BUT UNPROVEN
- **Pain real** (VERIFIED, but it's blog-volume not purchase intent): "My Agent Returned Success. The Browser State Said Otherwise", "Why AI Agents Say 'Done' When the Task Actually Failed", scrapeops/scrolltest pieces.
- **Best paying analog:** Coval (voice-agent testing) — $28M Series A, 60+ orgs incl. Zoom/Deepgram, public tiers **$100 / $500 / $4,500/mo**. Proves the band monetizes — BUT voice has forcing functions (contact-center buyer, compliance, per-minute cost) browser-agent testing lacks.
- **Different buyer:** Momentic (~$19M, Notion/Webflow/Retool) tests *your app*, not *your agent*.
- **Absorbers own the budget line:** LangSmith ($39/seat), Braintrust (Pro $249/mo), Langfuse ($29/$199) already own "agent eval in CI".
- **Strongest AGAINST:** individuals already ship near-identical free OSS — `homayoun-safarpour/agent-eval-workbench` (YAML scenarios + trace-grounded side-effect detection + exit-code CI gate), `emaxiss/groundtruth`. One-week DIY substitute exists.
- **De-risk:** get 3–5 teams shipping write-capable browser agents to say *in writing* they'd pay.

## Agent 2 — Competition & Platform Absorption → OCCUPIED BUT WINNABLE AT SMALL SCALE
- **NAME COLLISION:** `relari-ai/agent-contracts` already exists (21★, dormant since 2025-03, YC W24). Also `vahwali04/agent-contract-tests`. → **RENAME REQUIRED.**
- **Closest exact match:** `ChanTso/state-eval` — "SQL-graded business-state invariants, forbidden side effects, authorization ablations" (0★, research benchmark, no adoption).
- **Biggest absorption threat:** **Microsoft `responsibleai/ASSERT`** — 321★, daily commits, framework-neutral YAML CI invariants for "data isolation, payment authorization, irreversible tool actions"; trace-grounded today, needs only backend-DB + browser grounding to absorb this slice in ~12 mo.
- **Other:** Promptfoo (OpenAI-owned), Playwright Test Agents (owns assertions+traces+MCP), EvalView (trajectory diff, 136★), Momentic (names the "wrong-success" pain, solves with fuzzy AI assertions), Giskard (trace predicates), WASP/SecureWebArena/Thinkingbox/LegacyWorld (academic, check backend state on fixed sandboxes).
- **Whitespace:** real but THIN + converging — no *adopted* tool combines backend-ground-truth + side-effect policy + framework-neutral + statistical CI aimed at *your own app*.
- At ~5 customers crowding barely matters; must-dos: **rename** + **lead with failure modes incumbents structurally miss** (backend DB delta, silent 200-error-body, cross-tenant leak).

## Agent 3 — Kill-it Case & Solo Feasibility → BUILD ONLY AS ≤2-WK EXPERIMENT (lean KILL on revenue)
- **Name + concept taken** (relari, vahwali, arXiv "Agent Behavioral Contracts").
- **No defensible wedge (near-fatal):** "UI action → query the DB → assert the row" is a documented, mature **Playwright+DB E2E pattern** — a day of glue for a team that already has Playwright + a DB.
- **Frameworks self-fixing:** Browser Use shipped a built-in LLM-judge (Jul 2026) and fixed the exact false-completion bug — truncated runs now reported as truncated, not success (Aug 2026).
- **Security angle closing:** vendor browser-agent prompt-injection driven 35.7%→0% (Anthropic; exact % needs one confirming click); shrinks your red-team wedge.
- **WebMCP risk:** Browser Use already ships native WebMCP → structured tool-calls shrink the DOM-verification surface over 2–3 yrs.
- **Hardest part = deterministic staging-env state reset** — unsolved, per-stack, per-customer → consulting trap + credibility ceiling.
- **Problem IS real & large (VERIFIED):** false-positive 54–85% on DONE-signal runs; "belief failure" ~75% of intervention failures; 78%→22% benchmark-to-prod.
- **Genuine insight in your favor:** backend ground-truth is MORE deterministic than everyone's trajectory/LLM-judge approach — strong *if expressed as a benchmark*.
- **Recommends:** ≤2 weeks → public benchmark, reputation-only, strengths-aligned, no staging-reset dependency; let measured demand decide if a tool follows.

---

## What this means for the build (user is proceeding anyway)
If building, the audit says the ONLY way to not lose: (1) **rename** (agent-contracts is taken), (2) **wedge = the failure modes incumbents miss by construction** — backend DB delta, silent HTTP-200-with-error-body, cross-tenant leak, duplicate-on-retry — NOT generic eval, (3) **lead on determinism** (backend truth > trajectory/LLM-judge), (4) get **written WTP** from 3–5 teams before heavy investment, (5) treat **staging-state-reset** as the hard risk, not an afterthought.
