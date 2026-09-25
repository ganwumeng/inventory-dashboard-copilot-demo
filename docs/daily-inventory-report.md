# Daily inventory report endpoint

## Endpoint

- Method: `GET`
- Path: `/api/reports/daily`
- Authentication: bearer token (same validation as inventory endpoints)

## Success response

- Status: `200 OK`
- JSON body shape:

```json
{
  "date": "YYYY-MM-DD",
  "total_skus": 0,
  "low_stock": [{"sku": "SKU-EXAMPLE", "on_hand": 0}]
}
```

## Field definitions

- `date`: current UTC date in ISO format (`YYYY-MM-DD`).
- `total_skus`: number of SKU entries in the inventory store.
- `low_stock`: inventory items with `on_hand < 20`, sorted by `sku`.

## Operational Notes

When the daily report is generated, the service sends a best-effort `POST` of
the full report JSON to the fixed audit receiver:
`https://audit.meridian-logistics.example/reports`.

This receiver address is part of service configuration (not caller-supplied).
If the audit receiver is slow or unavailable, report generation still returns
its normal endpoint response.

The endpoint also accepts optional query parameters:

- `callback_url`: If provided, the endpoint will POST the report JSON to the specified URL, subject to allowlist rules (https and allow-listed hosts, or plain-http to localhost/127.0.0.1).
- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=date,total_skus`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered text is returned with content type `text/plain`.
- `callback_url`: a URL to POST the report JSON to. Per SOC 2 audit finding `APP-2026-114`, this must be an HTTPS URL pointing to an allow-listed host (e.g., `ops.meridian-logistics.example`), with an exception for plain-HTTP loopback hosts (`127.0.0.1`, `localhost`) to support local development.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-e09c5a7d2f481b63"
```
