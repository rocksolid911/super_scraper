# AI Cost Estimation Guide

Super Scraper uses Google's Gemini models for its Natural Language (NL) extraction engine. This document provides cost estimates for the different AI-powered features within the platform.

Cost minimization is a hard requirement for this project.

## Models Used

| Model | Role | Cost per 1M input tokens | Cost per 1M output tokens |
|-------|------|-------------------------|--------------------------|
| `gemini-2.5-flash-lite` | High-volume content extraction | $0.075 | $0.30 |
| `gemini-2.5-flash` | Low-volume planning & schema | $0.35 | $1.05 |

*Note: Pricing is subject to change. Refer to official Google Cloud / Vertex AI pricing pages.*

## Cost by Feature Turn

### 1. Natural Language Scrape Job (Single Page)
A standard prompt-based scrape job uses a LangGraph `planner → harvest` loop.

- **Planner (`gemini-2.5-flash`)**: Invoked once to create the extraction schema.
  - Input tokens: ~1k
  - Output tokens: ~100
  - Estimated cost: **~$0.0004**
- **Harvest (`gemini-2.5-flash-lite`)**: Invoked per DOM batch.
  - Input tokens: ~10k - 50k (depending on page size)
  - Output tokens: ~500
  - Estimated cost: **~$0.001 - $0.004** per batch
- **Total per page**: **~$0.0015 - $0.0045**

### 2. Conversational Refinement (Multi-turn)
When refining an extraction schema iteratively through the UI.

- Uses **Planner (`gemini-2.5-flash`)** per turn.
  - Input tokens (includes context history): ~2k - 3k
  - Output tokens: ~100
  - Estimated cost per turn: **~$0.001**

### 3. Visual Selector Inference
Inferring repeating containers and fields based on clicks (`/infer-selectors/`).

- *Currently, this path does not use LLMs (uses deterministic BeautifulSoup/Playwright).*
- Estimated AI cost: **$0.00**

### 4. Discovery Mode (Sections & Items)
Mapping a site's sections and list entries (`/discover-sections/`, `/discover-items/`).

- *Pure BeautifulSoup implementation. No LLM.*
- Estimated AI cost: **$0.00**

### 5. Universal Web-Search Scraper (Future Scope)
An agentic workflow that searches the web to find targets and then scrapes them.

- **Search Agent (`gemini-2.5-flash`)**: Multi-turn planning to execute web searches.
  - Estimated 3-5 turns per query.
  - Estimated cost per query: **~$0.005 - $0.01**
- **Harvest (`gemini-2.5-flash-lite`)**: Per target page found.
  - Estimated cost: **~$0.003** per target

## Caching & Optimization

- **CSS-Schema Caching**: After the first successful NL agent run on a page, a deterministic CSS schema is derived and cached. Subsequent runs on the same job **skip the LLM entirely**, reducing the AI cost of scheduled jobs to **$0.00**.
