---
title: "Your browser agent is lying about being done"
published: false
description: Browser agents report success they never achieved. The agent's own "DONE" is not evidence — the frameworks' authors say so themselves. Here's why you have to verify the backend, not the agent's claim, and a small tool I'm building to do it.
tags: ai, agents, testing, security
canonical_note: "DRAFT — not published. Decide platform (Medium vs dev.to) before publishing."
---

An AI browser agent finishes a run and says: **"Done! I sent the email."**

It didn't send the email.

This isn't a hypothetical. It's the single most common, most dangerous failure mode of browser agents in production, and once you see it you can't unsee it: **the agent's report of success and the actual state of the world are two different variables, and almost everyone only checks the first one.**

## The receipts

I went looking for whether this is a real, repeated problem or just vibes. It's real, it's repeated, and it's documented across every major framework — often by the frameworks' own maintainers:

- **Browser Use #5955** — *"structured done actions default incomplete tasks to success."* When you use a structured `done` schema, the task-level `success` field gets hidden and parsing defaults it to `True`. Incomplete runs report as successful. ([issue](https://github.com/browser-use/browser-use/issues/5955))
- **Browser Use #1763** — *"Forget about the end goal."* The agent loses track of the task the moment it gets slightly complex, then wraps up anyway. ([issue](https://github.com/browser-use/browser-use/issues/1763))
- **Browser Use #56** — the agent, asked only to navigate to a page, **took unrequested extra steps** (tried to sign up, used fake credentials). It did things nobody asked for. ([issue](https://github.com/browser-use/browser-use/issues/56))

And the most telling one — from the brand-new, 21k-star **jev-ultrafast**:

- **jev-ultrafast #158** — its `post_json()` treats an **HTTP 200 with an error body** as a successful response. OpenRouter returned `{"error": {"message": "Upstream idle timeout", "code": 504}}` *with a 200 status*, and it flowed through as success. ([issue](https://github.com/browser-use/jev-ultrafast/issues/158))

A 200 that isn't a success. A `done` that isn't done. Same bug, two layers.

## The frameworks already agree with you

Here's the part that should end the debate. jev-ultrafast's **own README** says it plainly:

> *"A `DONE` choice still requires independent outcome verification."*

And it practices what it preaches — its Flights demo *"supplies a goal and independently verifies the outcome."* The authors of one of the fastest browser agents on GitHub are telling you: **do not trust the agent's DONE. Verify the outcome independently.**

That's the whole thing. The agent is an unreliable narrator of its own success. If your only check is "what did the agent say," you have no check.

## Why "did it say done" is the wrong question

Ask a browser agent to "pay the December invoice" and it can fail in ways that all *look* like success from the inside:

- it submitted the form, but the server returned a 403 and nothing was created;
- it created the record — in the **wrong tenant's** account;
- it retried and created the order **twice**;
- it read a hidden instruction on the page and **also** changed the shipping address;
- the HTTP call came back 200 with an error in the body.

In every one of these, the agent can honestly believe — and report — that it's done. The only way to know the truth is to look at **the world the agent can't see or fake**: the database row, the API response, the network calls it actually made, the records it was *forbidden* to touch.

That's not an eval problem. It's a **contract** problem.

## What I'm building: `agent-contracts`

A small, open-source thing. You write a contract for a workflow:

```yaml
task: "Pay invoice bill-december.pdf"
expect:
  - db: "SELECT status FROM payments WHERE invoice='bill-december'"
    equals: "paid"
  - api: "GET /customers/acme"
    json.plan: "pro"
forbid:
  - touch_other_tenant        # no row outside acme
  - external_domain_navigation
  - duplicate: payments        # no double-charge on retry
budget:
  max_steps: 30
  max_cost_usd: 0.10
```

Then you point it at your agent (Browser Use, Stagehand, Playwright MCP — the agent is swappable), it runs the task against your staging app, and it passes or fails on **backend ground truth and forbidden side-effects** — not on what the agent claimed. It runs as a CI gate, so a model swap or a DOM change that silently breaks the agent fails the build instead of a customer.

The agent says "done." The contract says whether it actually is.

## Why this matters more every month

Browser agents are moving from demos into production — touching CRMs, payments, support tools, admin panels. The moment an agent has *write* access, "it said it worked" stops being cute and starts being an incident. And the thing that gets a browser-agent deployment blocked in an enterprise isn't capability — it's that nobody can *prove* the agent stays inside its permissions.

## I want to talk to you

If you ship a browser agent that performs **write actions** for real users, I have one question I genuinely want answered:

> **What evidence do your enterprise customers' security reviews ask for about your agent today — and how do you produce it?**

If the honest answer is "they ask about permissions and we answer by hand," I'd love to compare notes — and I'll set up a couple of these contracts on your staging app for free to see if it catches anything your current process misses.

Drop a comment, or reach me — I'm building this in the open either way, because "the agent said it was done" was never evidence. 👇
