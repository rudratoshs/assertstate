# AssertState — launch & go-to-market

> Referenced by FEATURE-SPEC §17. Purpose: launch the OSS engine + GitHub Action directly to market
> and drive adoption. There is **no willingness-to-pay gate** — we ship, announce, and let real usage
> and demand steer the commercial (P3) roadmap. "Agents report success while the backend is wrong" is
> a well-evidenced problem; this is the reusable, deterministic acceptance harness for it.

## 0. Launch posture
Ship directly:
- the OSS engine (`assertstate` CLI) + the composite GitHub Action, with the wedge demo front-and-centre,
- a public write-up of the thesis (trajectory ≠ application truth) + the demo,
- the seed contracts and the `report.html` evidence as the "see it catch a real bug" hook.

P3 commercial features (hosted parallel runs, regression history, signed evidence reports, SSO/RBAC,
cloud browsers) are a **demand-driven roadmap** — built as adoption and inbound pull for them appear,
not blocked behind a pre-launch validation gate.

## 1. What "traction" looks like (steer the roadmap, don't gate the launch)
1. **Retention** — teams wire the GitHub Action into a real repo and it runs on PRs *unprompted* a week later.
2. **Value proof** — it catches ≥1 failure their existing tests missed (their words, their data).
3. **Pull for P3** — inbound asks for hosted runs / history / signed reports / SSO → build those next.

## 2. Target profile — write-capable browser agents + a backend they can't fake
Teams that get burned by "agent said DONE, state is wrong":
- AI ops/automation startups (agentic SDR, billing/invoice, onboarding, RPA-replacement) writing to real DBs/CRMs.
- Internal agent teams at SaaS companies automating back-office flows on staging.
- Heavy users of Browser Use / Stagehand / Playwright-MCP / JEV.

Best fit: anyone who can name a concrete cost of a silent agent failure. (Read-only/research agents,
pure chat, and demo-ware with no real backend are weaker fits — lead with the others.)

## 3. Where to reach them (real anchors — NOT fabricated leads)
Mine the exact failure modes AssertState's seeds are grounded in, then reach the people in those threads:
- Browser Use: issues #5955 (structured `done` → false success), #1763 (lost the goal / wrong value), #56 (unrequested action).
- jev-ultrafast: #158 (200-with-error-body), #132 (stale action id), #120 (confidence shift).
- Browser Use / Stagehand Discords; YC AI-agent batch companies; GitHub search: `"agent reported success"`, `"said done"`, `"duplicate"`+`agent`, in agent repos.
- Launch surfaces: a Show HN / Loom, the thesis write-up, the agent-framework Discords, and the issue threads above.

## 4. The wedge demo (≤3 min) — "wait, my tests pass this?"
```
assertstate run contracts/pay-invoice.e2e.yaml --app demo --scenario slow_retry   # FAIL, exit 1
```
Agent reports DONE, every final-state check is green, yet it FAILs — a slow retry committed a duplicate
*after* the agent "finished," caught only by the settled DB delta. Open `report.html`. The line that lands:
**"your current eval passes this run; your database has two charges."** Record a 60-sec Loom of this — it is
the whole pitch.

## 5. Discovery / conversation script (ask, don't pitch)
1. "When your agent says it succeeded, how do you *know* it actually did?"
2. "Have you shipped a run that looked fine but corrupted state — duplicate, wrong tenant, half-write? What did it cost?"
3. "Do you re-run agents in CI, or once by hand?"
4. "Would you put this as a required check on your repo?" — **then stop talking and watch if they wire it in.**

## 6. Launch cadence
- **Wk 1:** publish the write-up + 60-sec wedge Loom; post to the agent-framework communities and the anchor issue threads; reply to new "agent said done" reports with the demo.
- **Wk 2:** help anyone leaning in get the Action running on their repo; collect the failures it catches as public proof; note which P3 asks recur → that is the roadmap signal.

---

## 7. Message templates (personalize the [brackets]; lead with their pain, not the tool)

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

### C. The ask (end of a good conversation)
> "Want this as a required check on [their repo] this week? If it catches something your tests miss,
> tell me — and tell me what hosted/history/signed-report features would make it worth paying for."

## 8. What I will NOT do here
- Invent named companies/buyers or fake traction.
- Make the repo public or publish to PyPI without your explicit say-so (a launch action, your call).
