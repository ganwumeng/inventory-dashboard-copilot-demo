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

When the daily report is generated with a `callback_url` query parameter, the
service sends a best-effort `POST` of the full report JSON to that callback.

Callback targets are restricted to:

- `https://ops.meridian-logistics.example/...` (production receiver allowlist).
- Plain `http://` loopback hosts (`127.0.0.1`, `localhost`, `::1`) for local
  development.

If the callback is invalid, blocked by policy, slow, or unavailable, report
generation still returns its normal endpoint response.

The endpoint also accepts optional query parameters:

- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=total_skus,low_stock`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered string is returned as the JSON response body.
- `callback_url`: optional callback target that receives a best-effort report
  `POST` when it matches the allowed callback policy above.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-0a6d94c8e2b75f13"
```
