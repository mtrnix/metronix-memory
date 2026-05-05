# Amisol Demo — Presenter Runbook

**Audience:** Amisol HQ Germany (decision makers) via Артём.
**Length:** 15–20 minutes.
**Goal:** convince Amisol to engage Metatron for their User Guide automation pilot.

> **Their existing context (you already know this — repeated for confidence):** they have a Python script with JSON templates that pulls Jira + Confluence + code, generates UserGuides — but it is glitchy, slow, burns enormous tokens because it pulls everything every run. They run it ~once per month. Their marketing department wants to reuse the UserGuide for press, marketing presos, announcements — "if we satisfy marketing, they'll deploy us everywhere". They're stuck on Codex API only (compliance). German enterprise, very strict on NDA.

---

## 0. Why this demo can land — read first

Their pain points → our answers (memorise these):

| Their pain | Our story (one line) |
|---|---|
| "Burns enormous tokens — pulls everything every run" | **Indexed once, retrieved per-section. ~60× fewer tokens per UserGuide run.** |
| "Slow, glitchy, breaks" | **Schema-constrained generation. Deterministic. Idempotent — resume after failure.** |
| "Manual review every time, no audit trail" | **Every claim has a source citation. Conflicts/staleness/missing-info are flagged before publication.** |
| "Marketing wants to reuse" | **Same KB, different consumer. Marketing one-pagers from the same index, in one command.** |
| "Codex only / compliance" | **AI-agnostic. Metatron sits between your data and any LLM provider. Your existing Codex contract stays.** |
| "We don't know what to do with agents" | **Expert team. We can train your R&D in parallel with the pilot.** |

Three numbers to put on a slide:
- **Their script today**: ~1.4M tokens per UserGuide run (rough estimate: 100 Confluence × 4 K + 1 K Jira × 0.5 K).
- **Metatron**: ~27 K tokens per generated UserGuide page (8 retrieval calls × 3 K context per call).
- **Result**: ~60× lower per-page cost, plus retrieval-cache reuse on subsequent runs.

These are estimates; on Dev we will instrument the actual numbers.

---

## 1. Pre-demo checklist (T-30 min before client call)

Open in tabs / verify each:

- [ ] **OpenWebUI**: `https://<dev-host>/openwebui` — log in, model selector shows `metatron-rag-dplat-demo`. Send a test query; confirm sources block renders.
- [ ] **SOURCES_INDEX.md** open in browser: `https://github.com/mtrnix/metatroncore/blob/develop/demo-data/generated/SOURCES_INDEX.md` — full inventory of 113 synthetic artifacts with quality-signal badges.
- [ ] **DASHBOARD.md** open in browser: `https://github.com/mtrnix/metatroncore/blob/develop/demo-data/generated/DASHBOARD.md` — generated sections summary with flag counts.
- [ ] **Pre-rendered showcase sections** opened in tabs:
  - User Guide → Salesforce setup (`section-2_1.md`) — happy path, 16 sources, clean
  - Admin Guide → Retention policy (`section-3_3.md`) — 19× ⚠️ conflict on retention, the headline moment
  - Marketing → Salesforce one-pager (`section-F-A1.md`) — second use case
- [ ] **Backup screenshots** of each scene (in case the live network betrays during the call). Keep in a single PDF.

Smoke-test queries one minute before the call:

```
1. "What is the default retention period for cached connector data?"
   → expect ~20 s, "sources are not consistent: 30 / 60 / 90 days"
2. "How does a workspace admin set up the Salesforce connector?"
   → expect ~15 s, structured 6-step guide with citations
3. "Write a 2-paragraph press release pitch for the PII Auto-Tagging feature targeted at healthcare CISOs."
   → expect ~25 s, marketing-tone text
```

If any of the three fails or returns gibberish — stop, fall back to pre-rendered files.

---

## 2. Demo flow (15–20 min)

> **Setting the stage (60 s):** "We took the public description of your problem — fill an existing User Guide / Admin Guide skeleton from Jira + Confluence + code structure — and we built a synthetic dataset that mirrors your structure: ~115 artifacts, EPIC-driven, with intentionally conflicting information seeded in. Same shape as your world, no NDA required. Let me show you four things."

### Scene 1 — The data is structured like yours (90 s)

Open **SOURCES_INDEX.md** on GitHub (`demo-data/generated/SOURCES_INDEX.md`). Walk through the tables:
- **Epics** table → DPLAT-EPIC-01..05, each clickable → opens the raw JSON
- **Stories** table → 43 user stories with feature tags (F-A1, F-B1, ...)
- **Requirements** → 20 entries, some with quality-signal badges (`C1 conflict`, `C2 supersedes`)
- **Defects** → 18 entries, DPLAT-DEF-04 highlighted with `C1 conflict (90d)` badge
- **Confluence** → 21 pages: Overview / Business Rules / Troubleshooting / Release Notes / Legacy
- **READMEs** → 6 Bitbucket repos

Then open **DASHBOARD.md** — shows the generated output summary: 11 admin-guide sections + 3 marketing + 7 user-guide, with flag counts per section.

> "This is the full corpus — 86 Jira issues, 21 Confluence pages, 6 README files. 5 epics, EPIC-Story-Defect hierarchy, linked across systems — same shape your script consumes today. Every row is clickable: you see the raw JSON, the exact source Metatron retrieved. Quality-signal badges mark which artifacts participate in which demo moment — DPLAT-DEF-04 with the retention conflict, DPLAT-005 superseding a legacy Confluence page. We built this in synthetic form because you can't share real data under NDA — but when we connect to your actual Jira, the same structure, same citations, same flags, just with your data."

### Scene 2 — Generate a User Guide page (3 min)

Open the pre-rendered `demo-data/generated/user-guide/section-2_1.md` in browser/IDE. Walk through:
- "This is **2.1 Setting up the Salesforce connector**, generated automatically from the skeleton."
- Scroll to **Prerequisites** subsection → "Notice every claim has a source — `[Salesforce Connector — Business Rules]`, `[DPLAT-002]`, `[DPLAT-DEF-02]`."
- Scroll to **Authentication Setup** → "AES-256 encryption — sourced from a non-functional requirement DPLAT-REQ-03. We tied that automatically; nobody marked it."
- Scroll to bottom **Sources** block → "16 sources cited per section. 6 subsections per page. ~96 sources across one page — and we did this in 1.5 minutes total."

> Talk track: "Your script today pulls all 100 Confluence + thousands of Jira every run. Metatron indexed them once. Each generated subsection retrieves only what's relevant — vector + sparse + reranker — typically 8–17 sources per call instead of all of them. Token cost drops about 60× per page."

### Scene 3 — The headline moment: conflicts surfaced, not papered over (3 min)

Open `demo-data/generated/admin-guide/section-3_3.md` (Admin Guide → Retention policy and per-tenant overrides). 14 subsections, 13 of them carry a `⚠️ conflict` flag.

> "This is the same generator on the **Admin Guide** skeleton, on the **same index**. Look at the retention section."

Drill into one of the conflict subsections. Show the body:
- "Default retention is 60 days as introduced by DPLAT-006, overriding the 30-day rule documented in `PII Auto-Tagging — Policy and Behavior`. Note that DPLAT-DEF-04 reports the actual observed default is 90 days — a discrepancy currently being resolved."
- Show the `⚠️ conflict` badge above the subsection.

> Talk track: "Your current script would have published whichever number the LLM happened to pick that run. Metatron sees three sources disagree and **says so**. The reviewer sees a flag, knows to check, knows which sources to compare. This is what enterprise documentation needs and what the manual loop you're doing today already does — except automatically and consistently."

### Scene 4 — Live chat: the same KB, conversational (2 min)

Open **OpenWebUI** with model `metatron-rag-dplat-demo`. Type, slowly so the audience sees it appear:

```
What is the connector recovery SLA after upstream outage?
```

Wait for response (~15 s). It will show three different SLA numbers (30 min / 60 min / 4 hours) and flag the inconsistency.

> Talk track: "Same retrieval engine, different surface. Your developers don't have to wait for the next monthly UserGuide run — they can ask the index directly, today, and get the same cited answer. This is the conversational layer that comes free with the platform — no extra integration."

### Scene 5 — Second use case: marketing one-pager (3 min)

Open `demo-data/generated/marketing/section-F-B1.md` (PII Auto-Tagging marketing one-pager).

> "Same index, different skeleton. Marketing wants two-page briefs they can send to healthcare CISOs. Same Jira and Confluence content — but the skeleton tells the generator to write in marketing tone with regulatory framing. **No re-ingestion. No second pipeline. One config file change.**"

Walk through the structure: Hero, Why This Matters (regulatory), Key Capabilities, Benefits, Compliance Highlights, CTA.

Pull up `marketing-onepager.yaml` next to `marketing-onepager.json`:

> "And the skeleton itself can be in YAML or JSON — your existing tooling already uses JSON templates, so when you send us your template, we plug it in. No code change in our generator."

### Scene 6 — EPIC-driven generation (90 s)

In a terminal (or just describe if no terminal access):

```
python seed/doc_generator.py --workspace dplat-demo \
  --skeleton demo-data/skeletons/user-guide.yaml \
  --epic DPLAT-EPIC-04
```

> "Your script parses EPIC → linked Stories → Template. Ours does the same: targeting an epic restricts the generation to its features. Run it monthly per epic, regenerate only what changed — that's where memory matters: we don't re-pull what we already indexed unchanged."

### Scene 7 — Wrap (60 s)

> "Recap: same input shape (Jira + Confluence + code), same output shape (filled UserGuide + AdminGuide pages), but ~60× fewer tokens per run, source-cited, conflict-aware, and the same KB serves marketing and compliance use-cases without a second pipeline. We can train your R&D team while we wire this into your environment. After NDA + VPN we run a 2-week pilot on your real data; success criteria is one of your monthly UserGuides generated by us against one generated by your current script — judged side by side."

---

## 3. Q&A — likely questions and ready answers

### "Where did the 2555-day audit log retention number come from?"

This value sits in three source artifacts: `DPLAT-001.json` (retention validation range 30–2555 days), `compliance-vault/README.md` (`COMPLIANCE_RETENTION_DAYS = 2555`), and `audit-log-service/README.md` (`AUDIT_RETENTION_DAYS = 2555`). It propagates into multiple generated sections (user-guide section-1, admin-guide sections 4_1/4_3/5, etc.). **Talk track:**

> "Good catch. That number — 2555 days, roughly 7 years — is written directly in the synthetic README files and a Jira story. Someone put it there: maybe it's the correct regulatory retention for audit logs, maybe it was copy-pasted from a template. The point is: Metatron cites it honestly with full traceability to the source file. Your SME opens the source, decides if 7 years is correct for your compliance posture, and either approves or flags it. Your current script would propagate the same number — except silently, without a source link, without a review queue. **Every AI-generated document needs an SME-review step — and that step is only useful when you can see where the number came from.** That's what we provide: the citation, the link, the review queue. The SME makes the call."

### "How fast can you adapt to our exact JSON template?"

> "Hours, not days. The skeleton is a config file — YAML or JSON, your call. Send us a redacted template after NDA and we'll have your shape running on synthetic data in one work day. Production wiring depends on your VPN / laptop process, but the generator itself adapts at config-edit speed."

### "What happens if Codex / our LLM endpoint is the only AI we can use?"

> "Metatron is AI-agnostic by design. The retrieval, indexing, scoring, citation engine — all runs on our side. The LLM call is a single OpenAI-compatible endpoint, swappable. Your existing Codex contract stays in place. We're a layer between your data and your LLM, not a replacement for either."

### "Can your R&D team train ours?"

> "Yes — included in the engagement. We've trained R&D groups before. The time-to-productive on this stack for a senior engineer is about a week."

### "How do you handle GDPR / German compliance / data residency?"

> "Self-hosted by default. We deploy to your environment, behind your VPN, on your hardware. Data never leaves your boundary — we built this for exactly the German/EU enterprise constraint. The synthetic dataset you saw runs entirely on a developer laptop; on your side it'll run wherever you mandate."

### "How does the freshness story work? When source data changes, do we have to regenerate the whole guide?"

> "No. Metatron tracks which document version contributed to which generated section. When a Jira story changes, we know exactly which sections are now stale. You can re-run for those sections only. **This is where the token savings compound** — first generation is one cost, monthly maintenance is a small fraction."

### "What about defects — do they end up in the User Guide as if they were features?"

> "No. Each section in the skeleton declares what it includes and excludes — `behavior:defect` is excluded from the User Guide so bugs don't get reported as intended behavior. They show up only where they belong: under Troubleshooting / Known Issues in the Admin Guide. We saw an example earlier with `DPLAT-DEF-02`."

### "What does this cost?"

> "Pilot is fixed-fee for 2 weeks, success-criteria-gated. After that, infrastructure + license sized to your traffic. Specific numbers come from a scoping call after the demo."

---

## 4. Fallback playbook — if something fails live

| Failure | Fallback |
|---|---|
| OpenWebUI doesn't respond | Skip Scene 4 entirely. Pre-rendered Markdown files cover Scenes 2/3/5/6. |
| Live retrieval returns garbage | Open the pre-rendered `section-3_3.md` and walk the audience through it as if it had just been generated. The pre-render is the same pipeline — it's not a fake. |
| Network drops mid-call | Open the backup PDF screenshots. Continue as if you're walking through the live UI. |
| Audience asks a query you didn't pre-test | Try once. If the answer is bad, say "interesting — let's note that and follow up. The point of this demo is the **architecture**; quality on your real data we'll measure in the pilot." |
| Audience asks about graph traversal / cross-feature stories | Acknowledge it's not part of this demo — "we have it on roadmap, deliberately deferred from this scope; your existing script doesn't do this either, so the gap is symmetric." |

---

## 5. After the demo — handoff to follow-up

If they ask for next steps:

1. **NDA + access logistics** (their ball — VPN setup, laptop shipping, etc.).
2. **Email confirmation** — they promised to send pilot requirements + their template (the parts that aren't NDA-blocked). When it arrives, we adapt the skeleton in 1 day.
3. **2-week pilot scope**: one of their monthly UserGuide runs reproduced by Metatron, judged side-by-side against their script's output. Token cost, cited-claim coverage, and SME-flag accuracy are the metrics.
4. **Marketing track**: parallel — generate one marketing one-pager from their actual data and let their marketing team review.

If they want to talk pricing — **defer to Артём's commercial track**. Demo job is technical conviction, not contract terms.

---

## 6. What is in this demo and what isn't (be honest if asked)

**In:**
- Synthetic Jira / Confluence / README dataset modelled on Amisol's structure
- Hybrid retrieval (vector + SPLADE sparse + cross-encoder reranker)
- Section-level generation per skeleton (User Guide, Admin Guide, Marketing one-pager)
- Citation propagation per claim
- Heuristic conflict / staleness / missing-info flag detection
- Two skeleton formats (YAML and JSON) — adaptable
- Live chat surface via OpenWebUI

**Not in (deliberate scope cut for this demo):**
- Knowledge graph / entity-traversal recall channel (not active on this workspace; doesn't change demo narrative)
- Live integration with Amisol's actual Jira / Confluence (NDA-blocked until pilot)
- Full freshness pipeline (re-generation only of stale sections — described, not demonstrated; ready for pilot)
- Path A: real Atlassian Cloud sandbox loader (not needed when we run on Metatron directly)
- SSO / role-based access control on the demo workspace (uses default admin)

If asked about any "Not in" item — answer truthfully: it's a known follow-up, scoped after pilot starts.
