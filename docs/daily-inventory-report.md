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

- `callback_url`: URL to which a best-effort `POST` of the report JSON will be sent. To comply with data delivery policies, the callback destination must be over HTTPS and the hostname must be within the `meridian-logistics.example` domain. For local development convenience, plain HTTP to loopback addresses (`127.0.0.1`, `localhost`, `[::1]`) is also permitted.
- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=date,total_skus`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered text is returned with content type `text/plain`.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily"
```
