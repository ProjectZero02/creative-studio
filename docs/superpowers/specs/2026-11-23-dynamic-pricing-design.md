# Dynamic Pricing Design

## Intent

Usage estimates should multiply the real token counts returned by Gemini by
current Google Cloud list prices. The estimate must not silently become stale
when Google changes a model price.

## Approaches considered

1. Keep the static rate card. This is simple, but requires manual updates and
   was rejected because it becomes stale.
2. Use the public Cloud Billing Catalog API with the existing Cloud Run runtime
   service account. This supplies dynamic list prices without storing an API
   key or granting the application access to billing-account data. This is the
   selected approach.
3. Use account-specific Pricing API data or BigQuery billing export. These can
   reflect contract pricing or actual charges, but are outside the requested
   list-price estimate and are delayed or require broader billing access.

## Design

- Terraform enables `cloudbilling.googleapis.com` alongside the existing
  required APIs and grants only the runtime identity permissions needed to call
  the API.
- The application uses Application Default Credentials/OAuth, never a service
  account key or API key.
- A pricing provider discovers the relevant public Vertex AI service and its
  SKUs, parses current token and media-unit rates, and caches the result for
  12 hours per process.
- Usage events continue storing the exact response token counts. They also
  store the applied input/output rates, pricing source, and effective time so
  historical estimates remain auditable.
- There is no static-rate fallback. If no fresh dynamic price is available for
  any billing unit, the event is recorded as unpriced and generation
  continues; the usage page excludes unavailable costs from dollar totals and
  reports the unavailable count separately.

## Non-goals

- Applying committed-use discounts, credits, taxes, or negotiated contract
  pricing.
- Replacing the usage page with a billing ledger or reconciling it to invoices.
- Adding service-account key files or putting project-specific values in
  Terraform source.

## Verification

- Unit tests cover OAuth request construction, token and media SKU parsing,
  twelve-hour cache expiry, unavailable pricing, and event persistence.
- Terraform formatting and validation run without applying infrastructure.
- Existing telemetry, usage, and app-import tests remain green.
