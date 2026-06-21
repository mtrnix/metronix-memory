# Metatron Core Roadmap

Last updated: June 2026. See [Strategy ADR](docs/adr/2026-04-25-metatron-strategy.md) for detailed architecture decisions.

## Legend

| Icon | Meaning |
|---|---|
| ✅ | Done |
| 🔨 | In progress |
| 📋 | Planned |
| 🔭 | Under consideration |
| 🎯 | Community — help wanted |

---

## Q2 2026 — Memory Quality Layer

| # | Feature | Status | Issue |
|---|---|---|---|
| 1 | Memory kinds: `fact`, `preference`, `pinned` | ✅ Done | — |
| 2 | Agent Context Assembler (constitution → preferences → memories → KB) | ✅ Done | — |
| 3 | 5-stage freshness pipeline (Linker → Reconciler → Monitor → Curator → DecisionEngine) | ✅ Done | — |
| 4 | Preference always-on injection (no retrieval needed) | ✅ Done | — |
| 5 | Cross-workspace isolation tests | 🔨 In progress | — |

---

## Q3 2026 — Enterprise Foundation

| # | Feature | Status | Issue |
|---|---|---|---|
| 6 | Public benchmarks (LoCoMo, LongMem, BEAM, BrainBench) | 📋 Planned | [MTRNIX-401](https://mtrnix.atlassian.net/browse/MTRNIX-401) |
| 7 | Temporal fact management (versioned facts, auto-invalidation, time-travel queries) | 📋 Planned | — |
| 8 | Synthesis layer (full answers with citations, not just chunks) | 📋 Planned | — |
| 9 | Gap analysis ("what does the brain NOT know yet?") | 📋 Planned | — |
| 10 | LiteLLM SDK migration in L3 `llm/` | 📋 Planned | — |
| 11 | LiteLLM provider → 100+ LLM backends | 📋 Planned | — |
| 12 | Channels extracted to external bot pattern (Telegram, Discord, Slack) | 📋 Planned | — |

---

## Q4 2026 — Agent + Ecosystem

| # | Feature | Status | Issue |
|---|---|---|---|
| 13 | Agent work-memory (indexed learnings from agent sessions) | 🔭 Considering | — |
| 14 | PluginManager supported public API with SemVer | 🔭 Considering | — |
| 15 | Contract tests in CI for plugin compatibility | 🔭 Considering | — |
| 16 | Community connector SDK (build your own connector in 10 lines) | 🔭 Considering | — |
| 17 | Permission model v2 (document/chunk-level ACLs) | 🔭 Considering | Trigger: first enterprise client |
| 18 | Control Center backend (agent registry, governance, observability) | 🔭 Considering | — |

---

## 2027+ — Platform

| # | Feature | Status |
|---|---|---|
| 19 | Multi-region / HA deployment | 🔭 |
| 20 | SOC 2 Type II + HIPAA compliance | 🔭 |
| 21 | SSO (SAML/OIDC) | 🔭 |
| 22 | 5-role RBAC with policy engine | 🔭 |
| 23 | Sidecar plugin architecture | 🔭 |
| 24 | Benchmark leaderboard (public, reproducible) | 🔭 |

---

## Competitive Gaps — We Need Your Help 🎯

These represent known gaps relative to competitors ([full analysis](https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/64454707)):

| Gap | Competitor | Priority | Help Wanted |
|---|---|---|---|
| Public benchmarks | Zep (LoCoMo 94.7%), Honcho (SOTA on 4), gbrain (BrainBench) | Critical | ✅ Benchmark design + execution |
| Synthesis layer (answers with citations) | gbrain (prose + graph + gap analysis) | High | ✅ Prompt engineering + retrieval integration |
| Temporal fact management | Zep (auto-invalidation, time-travel queries) | High | ✅ Graph schema design + freshness integration |
| Agent work-memory | Perplexity Brain (+25% correctness, +16% recall) | Medium | ✅ Session indexing + learning extraction |
| SOC2 / compliance | Zep (SOC2 Type II, HIPAA BAA) | Medium | ✅ Compliance expertise |

---

## Community Contributions

Tagged with [`good first issue`](https://github.com/mtrnix/metatroncore/labels/good%20first%20issue):

| Area | Examples |
|---|---|
| Documentation | Improve error messages, add docstrings, translate docs |
| Test coverage | Add unit tests for uncovered modules, edge cases |
| Connector helpers | Add utility functions for existing connectors |
| Small fixes | One-line bug fixes with clear reproduction |
| Examples | Add usage examples in `examples/` |

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

---

## Feedback

Roadmap priorities are shaped by:
- Pilot team feedback (internal)
- GitHub issues and discussions (community)
- Competitive landscape changes
- Enterprise client requirements

Open a [discussion](https://github.com/mtrnix/metatroncore/discussions) to propose or +1 a feature.
