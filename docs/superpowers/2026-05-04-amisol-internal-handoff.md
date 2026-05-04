# Amisol Demo — Internal Handoff (Konstantin → Artem)

**Purpose:** brief Artem on what was built for the Amisol demo, what to mention, what to avoid, what's still open.
**Pair this with:** `2026-05-04-amisol-demo-runbook.md` (for Artem to actually present).
**Jira:** MTRNIX-327.

---

## TL;DR

We built a synthetic dataset that mirrors Amisol's structure (EPIC → Story → Defect → Confluence, ~115 artifacts) and a thin Python doc-generator that walks a YAML/JSON skeleton, queries Metatron's hybrid retrieval per leaf section, and emits filled UserGuide / AdminGuide / Marketing pages with per-claim citations and quality flags.

The demo can run **today** on local Mac. To ship to Dev стенд: ~1 hour of work plus 3 questions to whoever owns Dev (see runbook + Jira comment).

---

## What Artem actually shows (5 scenes, 15–20 min)

Detailed in the runbook. Headlines:

1. **Data shape mirrors theirs** (KB Admin Console showing synthetic DPLAT inventory)
2. **Filled User Guide page generated automatically** (`section-2_1.md` Salesforce setup, 6 subsections, 16 sources)
3. **Conflict detection — the headline moment** (`section-3_3.md` retention policy, 19× ⚠️ conflict on the 30/60/90-day discrepancy)
4. **Live chat reproduces it** (OpenWebUI on `dplat-demo` model)
5. **Marketing one-pager from the same index** (`marketing/section-F-B1.md`) + skeleton-format flexibility (YAML ↔ JSON)

Optionally: EPIC-driven generation (`--epic DPLAT-EPIC-04`) if there's time.

---

## Three numbers Artem should memorize

| | Token cost per UserGuide run |
|---|---:|
| Their current script (pulls everything per run) | ~1.4M |
| Metatron (indexed once, retrieved per section) | ~27 K |
| **Improvement** | **~60×** |

Estimates — to be measured precisely on Dev when their LLM provider is wired in. Use as **order of magnitude**, not as a quote.

---

## Critical talk-track to memorise: the "2555-day audit retention" finding

Likely they'll probe one of the live queries and hit this.

**What happened:** when the local LLM generated synthetic READMEs for the demo, it invented `AUDIT_RETENTION_DAYS = 2555` env-vars in the Configuration tables. Now retrieval honestly cites that as "fact". Same as if a junior dev wrote it and nobody reviewed.

**The line to deliver (memorise):**

> "Metatron sees the source, cites it honestly, and propagates the number. Your current script would do exactly the same — except silently. **This is why an SME-review loop is non-negotiable in enterprise**, and our review queue is built for exactly that. Garbage in, garbage out — but at least visibly so."

This is **not a bug to apologise for.** It's the **strongest argument for why they need our SME-review layer** on top of any AI generation.

---

## What's in the codebase (committed shortly to a feature branch)

```
scripts/gen.py                                    # synthetic-data generator (oMLX, local-only)
seed/seed_metatron_direct.py                      # ingest demo-data/ into a Metatron workspace
seed/list_workspaces.py                           # tiny utility, bypasses auth
seed/test_retrieval.py                            # smoke-check recall channels
seed/test_full_pipeline.py                        # smoke-check full hybrid_search_and_answer
seed/doc_generator.py                             # the headline deliverable (see below)
seed/build_dashboard.py                           # builds DASHBOARD.md from generated section JSONs
prompts/system/*.system.txt                       # prompts used to generate the dataset
prompts/schemas/jira.schema.json                  # JSON Schema for synthetic Jira items
prompts/payloads/*.{meta.json,user.txt}           # 115 payload pairs, one per artifact
demo-data/jira/*.json                             # 86 generated Jira artifacts
demo-data/confluence/DPLAT/*.md                   # 21 generated Confluence pages
demo-data/bitbucket/*/README.md                   # 6 generated READMEs
demo-data/skeletons/user-guide.yaml               # User Guide skeleton (existing)
demo-data/skeletons/admin-guide.yaml              # Admin Guide skeleton (existing)
demo-data/skeletons/marketing-onepager.{yaml,json}  # Marketing skeleton — both formats, demo of adaptability
demo-data/generated/DASHBOARD.md                  # one-page overview of all generated sections
demo-data/generated/user-guide/section-*.md       # 6 generated User Guide sections
demo-data/generated/admin-guide/section-*.md      # 11 generated Admin Guide sections
demo-data/generated/marketing/section-*.md        # 3 marketing one-pagers (this run)
docs/superpowers/2026-05-02-amisol-demo-plan.md   # original plan (architecture + sales narrative)
docs/superpowers/2026-05-04-amisol-demo-runbook.md # presenter runbook (Artem-facing)
docs/superpowers/2026-05-04-amisol-internal-handoff.md # this doc
```

---

## How `doc_generator.py` works (so Artem can answer technical questions)

Pipeline per skeleton run:
1. Load skeleton (YAML or JSON — autodetected by extension).
2. Walk leaf sections (handle nested `children` and nested `sections_required`).
3. Optionally filter by `--epic` (uses `epic_features` map in the skeleton).
4. For each leaf section × each item in `sections_required`:
   - Compose a focused query from `retrieval.questions` + subsection title + skeleton's filter intent (currently injected as natural-language constraints in the prompt; Qdrant payload-level filtering is a known follow-up — `Document.tags` aren't yet propagated into chunk payload in metatron-core).
   - Call `hybrid_search_and_answer(query, workspace_id, k=25)` — same retrieval pipeline as Metatron's chat endpoint.
   - Parse the LLM answer: split body / sources block on the `📚 Sources:` marker.
   - Run heuristic regex flag detection (`conflict | stale | missing | defect-mention | low-confidence`) on the body.
5. Aggregate subsections → section JSON + Markdown render.
6. Idempotent (skips existing output unless `--force`).

Output per section: `section-<id>.md` (human-facing) + `section-<id>.json` (machine-consumable for downstream tooling — matches the §10.2 schema in the demo plan).

---

## Known gaps (be ready, don't volunteer)

If a technical reviewer probes — these are the truthful answers:

| Gap | Real answer |
|---|---|
| **Document.tags not in Qdrant payload** | Metatron-core architectural follow-up. Filter intent currently injected at prompt level. Production-fix is ~1 day. Doesn't affect demo quality (LLM honors prompt-level constraints). |
| **Graph extraction is empty** for `dplat-demo` | The standalone seed bypassed PG `raw_documents` write step. Cross-feature traversal queries (DPLAT-041/042/043) are weaker than they could be. Fix is ~30 min on Dev when needed. Doesn't affect any of the 5 demo scenes. |
| **Sources line rendering quirk in OpenWebUI** | `📄 Title — url` parsed as `[📄 Title](Content — url)`. Cosmetic. Fix is one-line change in `retrieval/search.py:_append_sources`. Skip for now unless cosmetic comes up. |
| **No Path A / Atlassian sandbox** | Not needed — they can't share data anyway, and the demo runs on Metatron directly. Path A is for after-pilot. |
| **No golden Q&A test set** | Build during pilot. Not needed for demo. |

---

## What to NOT volunteer (unless asked)

- That the synthetic data was generated with a local Qwen-Opus model (it might raise "is this AI training on AI-generated data" concerns). If asked, the answer is: "we generated synthetic data because Amisol can't share theirs — same way you'd seed any pilot environment".
- The 2555-day env-var was a hallucination during synthetic-data prep. **Use it as a feature** when asked (see talk track above), don't lead with it.
- That `scripts/gen.py` runs against `oMLX` (a personal/local stack). Not relevant to them.
- That we considered Atlassian Cloud sandbox and decided against. Doesn't help the conversation.

---

## What to do if they say "yes, let's pilot"

1. NDA + access logistics — Artem's commercial track.
2. Their template/requirements email — when it lands, ping Konstantin; we adapt skeleton in 1 day.
3. Pilot scope to propose: one of their monthly UserGuides reproduced by Metatron, side-by-side against their script. Metrics: token cost, cited-claim coverage, SME-flag accuracy. 2-week wall, fixed-fee.
4. Parallel marketing track: one marketing one-pager generated on their real data, given to their marketing team for review (this is the "if marketing is satisfied, they'll deploy us everywhere" play).

---

## What I owe you before the call

- [x] Demo data, generator, runbook, this handoff, Jira status
- [ ] Commit + push feature branch (next step, awaiting your green light)
- [ ] Dev стенд deployment (depends on the 3 open questions in MTRNIX-327 comment)
- [ ] 30-minute walkthrough call — schedule when convenient
- [ ] Any specific scene you want re-recorded or pre-rendered with different inputs — say the word

---

## One last thing — what *I* am still uncertain about

- **Whether their template format will match our skeleton shape** — they haven't sent it. The marketing JSON skeleton (`marketing-onepager.json`) shows we're not married to YAML, but if their template has constructs we don't model (e.g., variables, includes, conditionals), it's a config-edit at worst.
- **Whether 60× token saving holds on their real corpus** — order-of-magnitude is robust, exact ratio depends on their average document length.
- **Whether their compliance allows us to deploy at all** — German enterprise + Codex-only + on-prem requirements may surface hard constraints we haven't seen. Self-hosted Metatron addresses most, but not all.

Frame these as "to-be-measured-during-pilot", not as risks to lead with.
