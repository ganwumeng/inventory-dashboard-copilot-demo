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
the full report JSON to the URL provided in the `callback_url` query parameter.
If callback delivery is slow or unavailable, report generation still returns
its normal endpoint response.

Callback URL policy:

- `https` callbacks are allowed only for host
  `ops.meridian-logistics.example`.
- `http` callbacks are allowed only for local loopback hosts
  (`127.0.0.1`, `localhost`, `::1`) for local development.
- Callback path must match `/hooks/<probe-id>`, where `<probe-id>` uses
  letters, digits, and hyphens.

The endpoint also accepts optional query parameters:

- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=total_skus,low_stock`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered string is returned as the JSON response body.
- `callback_url`: callback destination to receive a best-effort POST copy of
  the full report JSON when it passes callback URL policy validation.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-c4d709e2b6a813f5"
```
