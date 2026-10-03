# Validation outreach — the only thing that answers "will anyone pay"

No more desk research. This is the conversation plan for **AssertState**. Goal: conversations with teams **running write-capable browser agents against a real app**. Start with the 4 problem-qualified leads; expand toward ~15. Kill or continue on what they do (not say).

**Positioning (one line):** *Existing tooling evaluates the agent (Browser Use benchmark/judge, LangSmith, Laminar). AssertState verifies the **application** — the real backend state after the run, not the agent's success claim.*

## Two-step qualification (don't lead with the security question)
The 4 leads are **problem-qualified** (they publicly hit the failure) — **not yet buyer-qualified** (unknown: do they run a write-capable agent for customers, sit in security reviews, hold budget?). So qualify in order:

**Step 1 — anchor to their failure + qualify the use case (first message):**
> "I saw your [repo] issue about [failure]. I'm building a small OSS tool that checks the actual application state after a browser agent runs, instead of trusting the agent's success claim. Are you currently running a write-capable browser agent against a real/staging app — and how do you verify the intended backend state actually changed (and that nothing else was touched)?"

**Step 2 — only after they confirm the use case:**
> "Does this ever become part of a customer/security review? What evidence do you provide today?"

**The offer (strongest next step):**
> "I'll wire up 2–3 of these checks against one of your workflows for free and see if it catches anything your current process misses."
This converts "would you pay?" into "will you give me a real workflow + access?" — far stronger evidence.

## The 4 problem-qualified leads (with channel + buyer-signal)
| Who | Issue / pain | Channel | Buyer signal |
|---|---|---|---|
| **@MahlerTom** (Tom Mahler, PhD) | Browser Use **#56** — unrequested actions + false "task completed" | **email via mahler.tech** | **High** — CEO @ Stealth, security-adjacent (PhD), building something |
| **@FunctionFreak** (Ashish Yadav) | Browser Use **#1763** — lost goal, premature done | **email aashish16yadav@gmail.com** | Medium — AI/ML engineer @ "SKY" |
| **@axisrow** | jev-ultrafast **#158** — 200-with-error-body = false success | **reply on jev #158** (very active there) | Medium — "AI agent tooling & automation" engineer, 113 repos |
| **@AmitHem** | Browser Use **#5955** — structured `done` → success | **reply on the issue** (thin profile, 4 repos) | Low — reach for pain-validation, not as a buyer |

(Draft messages for all four are prepared; MahlerTom is the one to prioritize.)

## Where to find the other ~11 (don't wait for them)
- Authors of other Browser Use / Stagehand / Skyvern issues containing "done"/"success"/"wrong"/"regression"/"injection".
- YC agent startups using Browser Use (20+ YC W25 cited by TechCrunch).
- Browser Use / Laminar Discord — people debugging write-action agents.
- Job posts mentioning "browser agent" / "computer-use agent" in production.
- The recruiting article comment section (a Show HN / dev.to post is the top of this funnel).

## Build timing — AFTER the first real workflow, not before
Do **not** build a generic demo first. Run the first 4 conversations, find one team with a real staging workflow, then build the tiny **Browser Use + Postgres + `db_delta`** slice **around that customer's workflow**. Sequence: **problem → real workflow → free proof → repeated use → money.**

## Signal hierarchy (protect against fooling yourself)
1. **Strongest:** someone pays / signs a concrete paid pilot or deposit.
2. **Very strong:** a team reruns it weekly *without you prompting*.
3. **Strong:** they give you a real staging env + real workflow.
4. **Medium:** they confirm existing tools can't establish the same fact.
5. **Weak (ignore as validation):** "cool idea", GitHub stars, issue/article engagement.

## Kill gate (end of ~week 2–4)
**Continue only if:** ≥2 paid pilots / written design-partner commitments **AND** ≥3 teams rerun weekly unprompted (strengthened: + a specific accepted price + named buyer).
**Kill** (→ publish the scenario corpus as a public benchmark + the article; reputation preserved) if: <~15 qualified conversations reachable; <5 teams run it on their own app; <3 real bugs caught that existing tools missed; **zero** paid pilots; or Playwright / Browser Use / Laminar / MS ASSERT ship backend-state + side-effect assertions during the window.

Downside hedged: even a "kill" leaves the OSS artifact, a cited benchmark corpus, and a strong article — all reputation, none wasted.
