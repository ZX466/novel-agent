---
name: deep-research
description: Multi-source web research with firecrawl/exa MCP. Search, deep-read, synthesize, deliver cited reports with source attribution.
metadata:
  origin: ECC
---

# Deep Research

> Drift-prone: MCP tool names and quotas change. Verify configured MCP tools and current docs before promising coverage.

## When to Activate

- User wants thorough research with evidence and citations.

## MCP Requirements

- firecrawl (web scrape/search) and / or exa (semantic search).

## Workflow

1. **Understand goal** — scope, questions to answer, output format (report/deck/memo).
2. **Plan research** — list subtopics and sources; parallelize per subtopic.
3. **Multi-source search** — run several queries; collect URLs + snippets.
4. **Deep-read key sources** — fetch full text; extract evidence notes (claim -> source URL).
5. **Synthesize** — group findings into themes; support each claim with citations.
6. **Deliver** — report structure:
   - Executive Summary
   - Major themes (each with cited findings)
   - Key Takeaways
   - Sources (URLs)
   - Methodology

## Quality Rules

- Cite real URLs; never fabricate sources.
- Distinguish fact vs. speculation.
- Flag conflicting evidence.
- Note recency/coverage limits.

## Parallel Research

- Use subagents (one per subtopic), then merge & reconcile.