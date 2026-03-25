# blank-coldfusion — CMS Content Publishing Pipeline (ColdFusion / CFML)

## What this template does

`content_publish.cfm` is an Adobe ColdFusion 2023 / Lucee 6 template that
implements a CMS content publishing pipeline for an e-commerce platform:

1. **cfquery SELECT_content** — reads the current content record from the SQL
   Server `cms_content` table, retrieving title, type, publish status, and
   current version number
2. **cfquery UPDATE_publish_status** — sets `publish_status = 'PUBLISHED'`,
   increments the version number, and records the publishing author and
   timestamp
3. **cfcache.flushAll** — flushes the ColdFusion application cache region
   corresponding to the content type (e.g. `content_category`)
4. **cfhttp.cdn_purge** — if the page has images, sends a CloudFront
   invalidation request via `cfhttp POST` to purge CDN edge caches
5. **cfhttp.search_index_sync** — if the page has associated products, sends a
   bulk reindex request to the Elasticsearch cluster to update product search
   results

## Why it has no observability

This is a **Tier D** legacy application. ColdFusion / CFML applications have no
OpenTelemetry SDK (Adobe provides no OTel agent for ColdFusion).

There are no HTTP sidecar calls, no trace headers, no span IDs — just
`cflog` entries in the ColdFusion application log.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `content_publish.cfm` to add `cfhttp` POST calls targeting the
   sidecar so that each publishing step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
