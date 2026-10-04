# Browser-Agent Outcome Verifier — Feature Document & Competitor Matrix

> **Working name: `AssertState` (PROVISIONAL).** `agent-contracts` is taken (Relari + vahwali). Before committing a name, run the full check — GitHub / npm / PyPI / domain / app store / trademark (lesson from the Pixense miss). Do not ship under `agent-contracts`.

**One-line thesis:** *Verify what a browser agent actually did — live backend DB/API state + forbidden side-effects — not what it reported as "DONE".*

**Target user:** a team shipping a **write-capable** browser agent (Browser Use / Stagehand / Playwright MCP / JEV) that faces enterprise security reviews. **Goal:** small revenue (~$500–2k MRR / 5–10 customers) + reputation — NOT a venture.

**Status:** Phase-0 scaffold exists (runnable contract CLI). This doc defines the full feature surface and where we sit vs the field.

> ⚠️ **Honest framing (from the 3-agent audit, [AUDIT-3-agents.md](AUDIT-3-agents.md)):** the *problem* is verified real; *willingness-to-pay is unproven*; the wedge below is genuinely unoccupied but thin and converging. Build gated on getting 3–5 written "I'd pay" commitments. This doc is the build spec, not a claim the market is proven.

---

## 1. The wedge — the one cell none of the 10 reviewed competitors fill

> **Scope note:** every "none / only / unique" claim in this doc is scoped to the **10 competitors + OSS projects reviewed on 2026-10-02** — finite research cannot prove universal absence. The claims are "none identified in the reviewed field," not "nobody anywhere."

Across the 10 reviewed competitors, **no single product combines these five on one axis:**

1. **Backend ground truth** as the pass/fail source (live DB/API after the action) — not DOM, not trace, not the agent's self-reported DONE.
2. **Forbidden side-effect policy** — wrong-tenant write, duplicate-on-retry, external-domain navigation, HTTP-200-with-error-body.
3. **Framework-neutral** across Browser Use / Stagehand / Playwright MCP / JEV.
4. **N-trial statistical verdict** (Wilson lower-bound), not a single flaky run.
5. **Pointed at *your own* staging app**, as a CI gate with an evidence bundle.

**Nearest rivals per dimension:** execution → **Momentic** (proprietary agent); security-policy framing → **Promptfoo** (BOLA/BFLA); CI-gated spec regression → **Microsoft ASSERT**; browser-agent support → **Laminar** (observes only); backend-SQL truth → **ChanTso/state-eval** (API-only, 0★). None assembles the full stack.

---

## 2. The field (10 competitors)

| # | Competitor | What it is | Stars (2026-10-02) | License | Biggest gap vs our axis |
|---|---|---|---|---|---|
| 1 | **Relari Agent Contracts** | trajectory pre/path/post-conditions (OTel) | ~21 (dormant; co. pivoted to robotics) | Apache-2.0 | no backend truth, no browser |
| 2 | **Microsoft ASSERT** | spec-driven behavioral regression + CI gate | ~321 (active) | MIT | judges traces, not live DB/side-effects |
| 3 | **Promptfoo** (OpenAI) | LLM/agent red-team + eval | ~25.6k | MIT | no backend-truth; Browser Provider is scripted, not agentic |
| 4 | **Momentic** | autonomous AI QA agent (closed) | n/a (SaaS) | closed | UI/visual/API checks, not backend ground truth; closed |
| 5 | **Giskard** | OSS LLM red-team/vuln scanner + Hub | ~5.9k | Apache-2.0 | no browser, no backend truth |
| 6 | **LangSmith** | agent tracing + trajectory eval | ~1.1k (SDK) | closed (SDK MIT) | observes/judges; never runs app or asserts state |
| 7 | **Braintrust** | eval/experiment platform + scorers | OSS pieces (?) | closed (SDK OSS) | score-over-output; no browser, no state |
| 8 | **Laminar** | browser-agent observability + replay | ~3.3k | Apache-2.0 | **observes** the agent; no verification/gate |
| 9 | **Playwright (+Test Agents+DB)** | the deterministic E2E substrate | ~96k | Apache-2.0 | **agentic test authoring/maintenance** (planner/generator/healer), but runtime tests are deterministic Playwright programs; backend truth + side-effect policy remain DIY |
| 10 | **OSS cluster** (state-eval, eval-view, agent-eval-workbench, groundtruth) | scattered prior-art repos | 0 / 136 / 0 / 1 | MIT/Apache | no single repo does the full stack |

**Vendor-owned adjacent systems (absorption watch):** Browser Use itself is moving into agent evaluation/CI — `browser-use/browser-use-rsi` ran YAML task definitions (`name/task/judge_context/max_steps`) judged in CI (archived 2026-09-25), and `browser-use/benchmark` (145★, active) ships an executor-vs-judge platform with saved trajectories/screenshots/evidence. **This does not fill our cell** — their verdict judges the *browser-agent run* (trajectory/outcome judge), not an *independent authoritative application-state oracle* — but it raises the absorption risk and is the clearest sign the frameworks are building their own eval. Watch it.

---

## 3. THE FEATURE MATRIX (every feature, micro → major)

**Legend:** ✅ Yes · ◑ Partial · ❌ No · ? Unknown · Ⓓ possible but hand-rolled/DIY

> **Matrix methodology:** ✅/◑/❌ describe **documented first-class product capabilities.** `Ⓓ` means the capability is achievable through arbitrary user-written code/custom evaluators but is **not a native product primitive.** This matters because, e.g., LangSmith's own docs say custom evaluators can contain arbitrary business logic including ground-truth matching — so "❌ backend DB assertion" means *not first-class*, not *impossible*. The whole thesis is providing the external-state oracle as a **declarative primitive**, not as "you could code it yourself."
**Columns:** **OUR**=AssertState · REL=Relari · AST=MS ASSERT · PF=Promptfoo · MOM=Momentic · GSK=Giskard · LS=LangSmith · BT=Braintrust · LAM=Laminar · PW=Playwright · OSS=cluster (best repo noted)

### A. Contract / test definition
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Declarative YAML contract | ✅ | ◑ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ◑ (a-e-w) |
| Preconditions / fixtures | ✅ | ✅ | ◑ | ◑ | ◑ | ◑ | ◑ | ◑ | ◑ | ✅Ⓓ | ◑ |
| Postconditions | ✅ | ✅ | ◑ | ✅ | ✅ | ✅ | ◑ | ◑ | ◑ | ✅Ⓓ | ◑ |
| Path / trajectory conditions | ◑ | ✅ | ✅ | ◑ | ◑ | ◑ | ✅ | ◑ | ◑ | ◑ | ◑ (eval-view) |
| Typed assertions (in/lte/regex/eq) | ✅ | ◑ | ◑ | ✅ | ◑ | ✅ | ◑ | ◑ | ◑ | ✅ | ◑ |
| Reusable / templated | ◑ | ? | ✅ | ✅ | ◑ | ✅ | ✅ | ✅ | ✅ | ✅ | ◑ |

### B. Outcome verification ← **core wedge**
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Backend DB assertion (live SQL)** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◑Ⓓ | ✅ (state-eval) |
| API/HTTP response assertion | ✅ | ❌ | ❌ | ✅ | ✅ | ◑ | ◑ | ◑ | ◑ | ✅ | ◑ |
| UI/DOM assertion | ◑ | ❌ | ❌ | ◑ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ◑ (groundtruth) |
| **Verify vs self-reported DONE** | ✅ | ◑ | ◑ | ❌ | ◑ | ❌ | ❌ | ❌ | ❌ | n/a | ◑ (state-eval) |
| **Detect HTTP-200-with-error-body** | ✅ | ❌ | ❌ | ◑Ⓓ | ◑ | ❌ | ❌ | ❌ | ❌ | ◑Ⓓ | ❌ |

### C. Side-effect / policy ← **core wedge**
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Forbidden-action policy | ✅ | ◑ | ✅ | ◑ | ❌ | ◑ | ◑ | ❌ | ◑ | ❌ | ◑ (a-e-w) |
| **Wrong-tenant / data-isolation** | ✅ | ❌ | ◑ | ◑ (BOLA) | ❌ | ❌ | ❌ | ❌ | ❌ | ◑Ⓓ | ✅ (state-eval) |
| **Duplicate-on-retry detection** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◑Ⓓ | ❌ |
| External-domain / allowlist nav | ✅ | ❌ | ◑ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◑ (route) | ❌ |
| Permission / authorization | ✅ | ❌ | ◑ | ✅ (BOLA/BFLA) | ◑ | ❌ | ❌ | ❌ | ❌ | ◑Ⓓ | ◑ |
| Destructive-action gating | ✅ | ❌ | ◑ | ◑ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### D. Agent / framework support
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Browser Use | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Stagehand | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Playwright MCP | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ? | ✅ | ❌ |
| JEV | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ? | ❌ | ❌ |
| OpenAI / Claude computer-use | ◑ (later) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ? | ❌ | ❌ |
| Framework-neutral core | ✅ | ◑ | ✅ | ✅ | ❌ | ✅ | ◑ | ✅ | ✅ | ◑ | ◑ |

### E. Security / red-team
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Prompt-injection as a contract scenario | ◑ | ❌ | ◑ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ◑ (groundtruth) |
| Jailbreak testing | ❌ | ❌ | ◑ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ◑ |
| Attack packs / plugin library | ❌ | ❌ | ◑ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ◑ |
| Adversarial scenario generation | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### F. Non-determinism handling
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| N-trial runs | ✅ | ❌ | ◑ | ◑ | ◑ | ◑ | ✅ | ✅ | ◑ | ◑ | ◑ (state-eval) |
| **Statistical verdict (Wilson/CI)** | ✅ | ❌ | ◑ | ❌ | ❌ | ❌ | ◑ | ◑ | ❌ | ❌ | ❌ |
| Flake handling / self-heal | ◑ | ❌ | ? | ◑ | ✅ | ◑ | ◑ | ◑ | ◑ | ✅ | ❌ |
| pass@k metric | ◑ | ❌ | ❌ | ◑ | ❌ | ◑ | ❌ | ❌ | ❌ | ❌ | ◑ (eval-view) |

### G. Execution / runtime
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Local browser | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ◑ | ✅ | ◑ (groundtruth) |
| Cloud / hosted browser | ◑ (later) | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ? | ◑ (Azure) | ❌ |
| Staging-env support | ✅ | ❌ | ◑ | ◑ | ✅ | ◑ | ❌ | ❌ | ❌ | ✅Ⓓ | ◑ |
| **State reset / seeding** (hard part) | ✅ | ❌ | ❌ | ❌ | ◑ | ❌ | ❌ | ❌ | ❌ | ✅Ⓓ | ❌ |
| Network capture (CDP/proxy) | ✅ | ❌ | ◑ | ❌ | ◑ | ❌ | ❌ | ❌ | ◑ | ✅ | ❌ |

### H. CI / CD
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GitHub Action | ✅ | ❌ | ✅ | ✅ | ✅ | ◑ | ❌ | ◑ | ❌ | ✅ | ◑ (eval-view) |
| Exit-code gate | ✅ | ◑ | ✅ | ✅ | ✅ | ◑ | ◑ | ◑ | ◑ | ✅ | ✅ (a-e-w) |
| PR / merge gating | ✅ | ❌ | ✅ | ✅ | ✅ | ◑ | ◑ | ◑ | ◑ | ✅ | ◑ |
| Regression baselines | ✅ | ❌ | ✅ | ◑ | ✅ | ◑ | ✅ | ✅ | ◑ | ✅ (visual) | ✅ (eval-view) |
| Model-swap diffing | ✅ | ❌ | ◑ | ✅ | n/a | ◑ | ✅ | ✅ | ◑ | n/a | ❌ |

### I. Observability / evidence
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Traces | ◑ | ✅ | ✅ | ◑ | ✅ | ◑ | ✅ | ✅ | ✅ | ✅ | ◑ |
| Replay (session/time-travel) | ◑ | ◑ | ✅ | ◑ | ✅ | ? | ◑ | ◑ | ✅ | ✅ | ❌ |
| **Evidence bundle / export** | ✅ | ◑ | ◑ | ◑ | ✅ | ◑ | ◑ | ◑ | ◑ | ✅ | ✅ (a-e-w) |
| JUnit / HTML reports | ✅ | ❌ | ? | ✅ | ? | ? | ◑ | ❌ | ❌ | ✅ | ◑ |
| Audit artifacts | ◑ (later) | ◑ | ✅ | ◑ | ◑ | ◑ | ◑ | ◑ | ◑ | ✅ | ◑ |

### J. Cost / latency
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Cost tracking | ◑ | ❌ | ? | ✅ | ◑ | ? | ✅ | ✅ | ✅ | ❌ | ❌ |
| Cost budget (fail over $) | ✅ | ❌ | ❌ | ◑ | ◑ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Latency budget / metrics | ✅ | ❌ | ? | ✅ | ? | ? | ◑ | ◑ | ✅ | ◑ | ❌ |

### K. Delivery / business
| Feature | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Open source | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Permissive license | ✅ (Apache-2.0) | ✅ | ✅ | ✅ | ❌ | ✅ | SDK-only | SDK-only | ✅ | ✅ | ✅ |
| Self-host | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ◑ (ent) | ◑ (ent) | ✅ | ✅ | ✅ |
| Hosted SaaS | ◑ (later) | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◑ | ❌ |
| SSO / RBAC | ◑ (later) | ? | n/a | ✅ (ent) | ✅ (ent) | ✅ (ent) | ✅ (ent) | ✅ (ent) | ? | n/a | ❌ |
| Paid tiers ($) | later | — | free | free+Ent | $0/$125/Ent | free+Ent | $0/$39/Ent | $0/$249/Ent | free+? | free(+Azure) | — |

### L. Adoption (context — not a feature, but decisive)
| Metric | OUR | REL | AST | PF | MOM | GSK | LS | BT | LAM | PW | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GitHub stars | 0 | 21 | 321 | 25.6k | n/a | 5.9k | 1.1k | ? | 3.3k | ~96k | 0/136/0/1 |
| Funding (ESTIMATE) | — | ~$500K | MS | ~$23M→OpenAI | ~$19M | ~$5M | ~$125M¹ | ~$36M | YC S24 | MS | none |
¹LangChain overall, not LangSmith alone.

---

## 4. Our full feature spec (every feature, by build phase)

**Phase 0 (done — scaffold):** YAML contract schema, contract load/validate, CLI that prints the check-plan, example contract, Apache-2.0.

**Phase 1 (MVP — the wedge):**
- Browser Use adapter (run a task, capture trace).
- **Backend DB probe** (live SQL assertion) + **API/HTTP probe**.
- **Verify-vs-DONE**: pass/fail from ground truth, never the agent's claim.
- **Forbidden side-effects:** wrong-tenant, duplicate-on-retry, external-domain nav, HTTP-200-with-error-body.
- Typed assertions (`in`/`lte`/`eq`/`eq_canonical`/`regex`).
- N-trial runner + **Wilson lower-bound verdict**.
- Budget caps (steps/cost/time).
- Network capture (CDP/proxy) for side-effect checks.
- Exit-code CI gate + **GitHub Action** + JUnit/HTML + **redacted evidence bundle** (per-run directory: run.json, trials/, junit.xml, report.html, manifest.json).
- Bundled demo app + 8 shipped example contracts (scenarios 1–6, 8, 9); scenarios 7 and 10–12 are deferred — see the ship/deferred breakdown in [scenarios.md](scenarios.md).

**Phase 2 (reach):** Stagehand + Playwright MCP + JEV adapters; model-swap regression diffing; staging state-reset helpers; richer evidence/audit bundle for security reviews.

**Phase 3 (commercial, only if WTP proven):** hosted parallel runs; regression history; signed evidence reports for procurement; SSO/RBAC; cloud browsers.

**Explicitly NOT building:** another browser agent; a faster JEV; generic LLM eval/leaderboards (LangSmith/Braintrust own it); jailbreak/attack-pack library (Promptfoo owns it); trace-viewer/replay (Laminar/Playwright own it); runtime "action-integrity" safety layer (Acira/Noma own it).

---

## 5. Our differentiators — the cells only we fill

1. **Backend ground truth as the verdict** (live DB/API) for a **real browser agent** — only state-eval does the SQL part, and it has no browser + 0 adoption.
2. **Forbidden side-effect policy** as declarative contract lines — duplicate-on-retry and HTTP-200-with-error-body are checked by **nobody** here.
3. **Framework-neutral across Browser Use / Stagehand / Playwright MCP / JEV** — Laminar observes them but doesn't verify; everyone else ignores browser agents.
4. **N-trial Wilson verdict for a browser-agent flow** — nobody advertises a formal statistical pass/fail for this.
5. **One YAML contract** spanning agent run + backend truth + side-effect policy + CI gate + evidence bundle.

---

## 6. Honest risks to design around (from the audit + this research)
- **Name taken** → rename + full availability check before launch.
- **Playwright is the absorption threat** (96k★, owns CDP/DBⒹ/assertions/traces/Action/Test Agents) — if it ships a declarative side-effect policy + agent adapter, the DIY gap closes. Lead on the things it has *only* as DIY: the declarative policy + statistical verdict + framework-neutral contract.
- **Microsoft ASSERT** (321★, daily) needs only backend+browser grounding to absorb this — move while it's trace-only.
- **WTP unproven + a 1-week DIY substitute exists** (Playwright+DB) → the product must be *materially less work than the DIY*, and you must get **3–5 written pay commitments** before heavy build.
- **Buyer pool is small** (write-capable-browser-agent teams) → the demo/article must find exactly them.

---

## 7. Sources
Per-competitor sources are inline in the research (Relari, MS ASSERT, Promptfoo, Momentic, Giskard, LangSmith, Braintrust, Laminar, Playwright, and the OSS cluster repos), captured 2026-10-02. Funding/customer figures are press/ESTIMATE; stars VERIFIED at fetch; several pricing/LLM-host details flagged UNKNOWN in the raw research.
