# AssertState — WTP validation & outreach

> Referenced by FEATURE-SPEC §17. Purpose: resolve willingness-to-pay with **conversations**, and
> **disprove** "this is a SaaS" as fast as prove it. P3 (hosted/SSO/signed reports/cloud browsers)
> stays unbuilt until this gate passes. "Real problem" is already supported; "validated SaaS" is not.

## 0. The gate (do not move it)
Build P3 only with ALL of:
- **3–5 qualified teams** shipping *write-capable* browser agents against a real backend,
- each with **a specific use case** where a silent agent failure actually costs money,
- **a named owner/buyer** (not "a dev who liked it"),
- **a specific price said out loud and accepted**, and
- **≥1 paid pilot or deposit.**

Short of a paid pilot → "real problem, unvalidated SaaS" → keep it OSS, do not build P3.

## 1. Signals that justify building P3
1. **Retention** — they wire the GitHub Action into a real repo and it runs on PRs *unprompted* a week later.
2. **Value proof** — it catches ≥1 failure their existing tests missed (their words, their data).
3. **Money** — a named owner accepts a specific number and pays a pilot/deposit.
All three → build. Two → nurture. One/zero → **do not build.**

## 2. Kill criteria (be honest)
Stop and keep it OSS/reputation if: nobody re-runs it; the pain is "nice-to-have"; they'd use it free
forever but won't pay; or the moat looks absorbable (a framework ships its own backend-grounded judge).
In that world AssertState is a **reputation asset** (OSS + the write-up), not a SaaS — a fine outcome.

## 3. Target profile — write-capable browser agents + a backend they can't fake
Teams that get burned by "agent said DONE, state is wrong":
- AI ops/automation startups (agentic SDR, billing/invoice, onboarding, RPA-replacement) writing to real DBs/CRMs.
- Internal agent teams at SaaS companies automating back-office flows on staging.
- Heavy users of Browser Use / Stagehand / Playwright-MCP / JEV.

Disqualify: read-only/research agents, pure chat, demo-ware with no real backend, anyone who can't name a cost of a silent failure.

## 4. Where to source (real anchors — NOT fabricated leads)
Mine the exact failure modes AssertState's seeds are grounded in, then contact the people in those threads:
- Browser Use: issues #5955 (structured `done` → false success), #1763 (lost the goal / wrong value), #56 (unrequested action).
- jev-ultrafast: #158 (200-with-error-body), #132 (stale action id), #120 (confidence shift).
- Browser Use / Stagehand Discords; YC AI-agent batch companies; GitHub search: `"agent reported success"`, `"said done"`, `"duplicate"`+`agent`, in agent repos.

**Target table (fill as you source — I did not invent names):**

| # | Team/handle | Where found (issue/Discord/YC) | Write-capable? backend? | Failure mode they hit | Named owner | Status |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  | to contact |
| … (aim for 15 sourced → 3–5 qualified) |

## 5. The wedge demo (≤3 min) — "wait, my tests pass this?"
```
assertstate run contracts/pay-invoice.e2e.yaml --app demo --scenario slow_retry   # FAIL, exit 1
```
Agent reports DONE, every final-state check is green, yet it FAILs — a slow retry committed a duplicate
*after* the agent "finished," caught only by the settled DB delta. Open `report.html`. The line that lands:
**"your current eval passes this run; your database has two charges."** Record a 60-sec Loom of this.

## 6. Discovery script (ask, don't pitch)
1. "When your agent says it succeeded, how do you *know* it actually did?"
2. "Have you shipped a run that looked fine but corrupted state — duplicate, wrong tenant, half-write? What did it cost?"
3. "Do you re-run agents in CI, or once by hand?"
4. "What would you pay to block a PR when the agent silently breaks state?" — **then stop talking.**

## 7. Two-week cadence
- **Wk 1:** 60-sec wedge Loom; source 15 teams into §4 table; 10 personalized outreaches/day anchored on *their* failure mode.
- **Wk 2:** 5–8 discovery calls; for anyone leaning in, get the Action running on their repo; ask the price question every call; tally against §0.

---

## 8. Message templates (personalize the [brackets]; lead with their pain, not the tool)

### A. GitHub issue-thread reply (warmest — they already reported the pain)
> Ran into this exact class of bug ([their issue]: agent reports success, state says otherwise).
> I built a small OSS harness that decides pass/fail from the app's own DB/API + settled side-effect
> deltas instead of the agent's self-report — it catches the "said DONE, committed a duplicate on a
> slow retry" case your tests pass today. 60-sec demo: [loom]. Curious if this maps to what bit you —
> happy to wire it against your flow.

### B. Cold DM / email (≤5 sentences)
> Subject: your [billing/onboarding] agent says "done" — is the row actually right?
>
> You're shipping write-capable browser agents against a real backend. The failure that's hard to
> catch isn't a crash — it's the run that looks successful but wrote a duplicate / wrong-tenant /
> half-record, which your current evals pass. I built an OSS gate that reads the app's own DB/API
> (not the agent's claim) and fails the PR when state is actually wrong — [loom, 60s]. If you've hit
> a silent-state-corruption bug, worth 15 min? I'll run it against one of your flows live.

### C. The ask (end of a good call)
> "Would you put this as a required check on [their repo] this week, and — if it catches something your
> tests miss — is that worth $[N]/mo to your team? Who'd own that call?"

## 9. What I will NOT do here
- Invent named companies/buyers or fake traction.
- Build P3, publish to PyPI, or make the repo public — all gated on the §0 outcome (and your say-so).
