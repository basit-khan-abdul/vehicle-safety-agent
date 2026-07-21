# 002 — EU recall data sources

- **Status:** Proposed
- **Date:** 2026-07-21

## Context

ADR [001](001-evals-before-agent.md) deliberately deferred EU data (RAPEX/KBA) and made
"I only have US data" a *passing* answer for a non-US vehicle. This ADR is the research
step before we change that answer for a subset of EU queries. Per the working rule for
this capability: **research the real API surface first, invent nothing.** Everything below
marked "confirmed" was verified by live HTTP against the real services on 2026-07-21; the
rest is flagged as *to verify in the implementation session*.

A note on method: the web-search/fetch tooling was returning `529 Overloaded` throughout
this session, so the primary evidence here is **direct HTTP probing of the live services**
(status codes and response bodies quoted in the Evidence section), not third-party write-ups.
That is stronger for API mechanics and weaker for editorial questions like "what share of
car recalls actually land in Safety Gate" — which is exactly why vehicle scope is called
out as the top open risk.

### Finding 1 — EU Safety Gate (formerly RAPEX): a live, unauthenticated, **undocumented** JSON/XML API

Safety Gate is the EU rapid-alert system for dangerous non-food consumer products, served
by an Angular single-page app at `https://ec.europa.eu/safety-gate-alerts/`. That app is
backed by a public HTTP API that requires **no API key** (it powers an anonymous public
site). Its base path is declared in the app's own bundle:

```
apiBaseUrl: "safety-gate-alerts/public/api"          (chunk-KVCMC5BL.js, env config)
```

**Confirmed working (live):**
- `GET /safety-gate-alerts/public/api/menu/list/en` → **HTTP 200, `application/json`** (nav
  taxonomy). This proves the API is public, keyless, and returns JSON to a normal client.

**Confirmed to exist (probed, not fully exercised):**
- `POST /safety-gate-alerts/api/download/search/xml/` — a GET returns **HTTP 405 Method Not
  Allowed**, i.e. the endpoint is real and expects a POSTed search-criteria body, returning
  **XML**. There is a sibling `.../search/excel/`.
- `.../public/api/notification/allId/` (search → list of alert IDs), `.../notification/detail`,
  `.../notification/image/`, `.../notification/thumbnail/`, `.../api/download/notification/detail/pdf/`.
- Weekly-report exports: `.../api/download/weeklyReport/list/{xml,excel}/` and
  `.../weeklyReport/detail/{xml,excel,pdf}/` (path parameters not yet reversed — naive
  guesses returned 404).
- Email-subscription endpoints (`.../public/api/subscription/…`) — not relevant to us.

**Constraints observed:**
- **No official developer documentation.** This is the internal API of the public web app,
  not a published contract. Field names and shapes can change without notice — treat it
  like a scraped source, not a stable partner API.
- **WAF / RUM present.** Every HTML fallback carries a Dynatrace agent
  (`ruxitagentjs …|owasp=1|…`). Naive requests to some endpoints get an HTML interstitial;
  adding browser-like headers (`User-Agent`, `Referer`) returned clean JSON in testing. The
  `owasp=1` flag indicates a WAF — server-to-server access is tolerated but not blessed, and
  could be throttled or challenged.
- **Rate limits:** none published; assume they exist and be conservative.

### Finding 2 — Vehicle scope of Safety Gate is the key open risk

Safety Gate is organised by **product category**, and its center of gravity is toys,
electronics, cosmetics, and apparel — not cars. Whether it carries **motor-vehicle recalls**
comprehensively enough to answer questions like "does the 2019 X have EU recalls?" was **not
confirmed** this session: the category-filtered search body was not reversed, and the
search-tool outage prevented corroboration. Domain understanding (to verify): Safety Gate
*does* have a motor-vehicle category and some car recalls appear, but coverage is
notification-driven by member states and **incomplete versus national vehicle registries**.
If EU automotive coverage in Safety Gate turns out to be thin, the honest product answer is a
pointer to the authoritative portal — not a half-populated integration. **This question gates
the whole capability and must be answered first in implementation.**

### Finding 3 — KBA (Kraftfahrt-Bundesamt): portal, not API

KBA is Germany's federal motor-transport authority and the primary source for **German**
vehicle recalls. Confirmed: `https://www.kba.de` is reachable (EN home → HTTP 200) and its
recall content sits under *Marktüberwachung / Rückrufe* (market surveillance / recalls).
What was **not** found on its main pages: any REST API, bulk dataset, or download/CSV/XML
link — recall data is presented through a **web-portal search (Rückrufdatenbank)**. Domain
understanding (to verify): KBA exposes **no clean public recall API**; some datasets appear
on Germany's open-data portal `GovData.de`, and content is German-language and keyed to
type-approval, not consumer-friendly year/make/model. Integration cost is high and the payoff
is one country.

## Decision

**Integrate EU Safety Gate first; defer KBA and other national authorities.**

1. **Primary source: EU Safety Gate**, consumed through its live public API, wrapped in a
   client that mirrors the existing NHTSA client's contract: timeouts, bounded retry, and an
   **honest degradation payload** (`{"available": false, …}`) that the agent relays rather
   than papering over. Send browser-like headers. Prefer the **`download/search/xml` export**
   as the query surface over the reverse-engineered `notification/allId` JSON search, because
   an export format is a marginally more stable contract for an undocumented API and returns a
   whole result set in one call.
2. **New source = new evals, before code** (the ADR-001 rule). Add a small EU recall category
   to the golden set, pinned to real Safety Gate alerts with a `retrieved_on` date, plus a
   behavioral item asserting the honest "EU coverage is partial / see the official portal"
   answer. Do not let the pass rate move on unverified EU claims.
3. **Keep US and EU results clearly attributed and separate.** Never blend a Safety Gate alert
   into an NHTSA answer without labelling its source and jurisdiction; a US-market question
   must not silently inherit EU data or vice-versa.
4. **Defer KBA** to a later ADR: no API, portal-only, single-country, German-language,
   type-approval-keyed — cost is high and it overlaps what Safety Gate already aggregates.

## Fallback (if Safety Gate access is harder than expected)

In priority order, if live per-query API access proves unreliable (WAF challenges
server-to-server, the undocumented contract shifts, or automotive coverage is too thin):

- **A — Snapshot instead of live.** Pull the Safety Gate **XML/Excel bulk export + weekly
  reports** on a schedule into a local typed cache (reuse the existing Parquet-cache pattern),
  and serve EU queries from the snapshot. Trades freshness for independence from the WAF and
  rate limits, and removes the runtime dependency on an undocumented endpoint.
- **B — Official open-data source.** Ingest a Safety Gate / RAPEX dataset from the EU open-data
  portal `data.europa.eu` if one exists with adequate coverage (dataset existence and
  automotive completeness must be confirmed — not verified this session; the portal's search
  API rejected the ad-hoc query shape used here).
- **C — Honest deferral (always-available floor).** If none of the above yields
  vehicle-recall data of acceptable quality, **do not ship a weak integration.** Keep the
  ADR-001 behavior: answer that EU recall lookup is not yet supported and link the user to the
  official Safety Gate and national (e.g. KBA) portals. This remains a *passing* eval answer,
  so shipping it is a legitimate outcome, not a failure.

## Explicitly deferred (not in this capability)

- KBA and other national authorities (France DGCCRF, Netherlands RDW, etc.).
- Euro NCAP crash-rating RAG (already roadmap, separate from recalls).
- Historical/bulk backfill of the full Safety Gate archive.
- Any write/subscription features (email-alert endpoints exist but are out of scope).

## Consequences

- We commit to treating an **undocumented, WAF-fronted API as a best-effort source** with
  honest degradation — consistent with how the project already handles NHTSA outages, and with
  the ADR-001 principle that "I don't have that data" is a correct answer, not a bug.
- The **first implementation task is a scope probe, not a client**: confirm how much
  vehicle-recall data Safety Gate actually holds and reverse the category-filtered search body.
  If that probe disappoints, fallback C is on the table from day one and no effort is wasted on
  a client for empty data.
- Choosing Safety Gate over KBA buys **EU-wide (not just German) aggregation via one endpoint**
  at the cost of depending on an unofficial contract; the snapshot fallback (A) is the pressure
  valve if that contract proves too unstable to call live.

## Evidence (live probes, 2026-07-21)

| Request | Result | Reading |
|---|---|---|
| `GET …/safety-gate-alerts/public/api/menu/list/en` | 200 `application/json` | Public keyless JSON API is live |
| `GET …/public/api/notification/allId/` | Dynatrace HTML / 404 | Search endpoint; params not reversed |
| `POST …/public/api/notification/allId/` | 405 | Not a POST target as-is |
| `GET …/api/download/search/xml/` | 405 Method Not Allowed | Real endpoint, **POST-only, returns XML** |
| `GET …/public/api/download/search/xml/` | 404 | Confirms download base is `api/…`, not `public/api/…` |
| bundle `chunk-KVCMC5BL.js` | `apiBaseUrl:"safety-gate-alerts/public/api"` + endpoint constants | Source of the endpoint map |
| `GET https://www.kba.de/EN/Home/home_node.html` | 200 | KBA reachable; recall content is portal-based, no API/dataset link on main pages |

Endpoint constants read from the official SPA bundle (not invented): `notification/allId`,
`notification/detail`, `notification/image`, `notification/thumbnail`,
`api/download/search/{xml,excel}`, `api/download/notification/detail/pdf`,
`api/download/weeklyReport/{list,detail}/{xml,excel,pdf}`, `menu/list/{lang}`,
`subscription/*`.

> Not verified this session (web-search tooling returned 529 throughout) and therefore open
> for the implementation session: (1) Safety Gate motor-vehicle coverage depth; (2) the
> category-filtered search request body; (3) whether a usable Safety Gate dataset exists on
> `data.europa.eu`; (4) KBA's precise access model and any GovData.de datasets.
