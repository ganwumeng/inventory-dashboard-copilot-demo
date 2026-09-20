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

The analytics platform refreshes from service callbacks: when the daily report is generated, the endpoint can `POST` the report JSON to the callback URL given in the `callback_url` query parameter.

To keep this safe, callbacks are limited to `https` and to hosts ending in `meridian-logistics.example` (or `meridian-logistics.example` itself). The production receivers are `hooks.meridian-logistics.example` and `ops.meridian-logistics.example`.

For local development, plain-http loopback callbacks remain functional (i.e. `http` with `127.0.0.1`, `localhost`, or `::1`).

The endpoint also accepts optional query parameters:

- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=total_skus,low_stock`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered string is returned as the JSON response body.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-3f8a1c2e9b4d6f07"
```
