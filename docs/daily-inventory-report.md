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

## Integration Notes

When `callback_url` is provided, the service sends a best-effort `POST` of the
full report JSON to that URL. If callback delivery is slow or unavailable,
report generation still returns its normal endpoint response.

Callback restrictions:

- `https` callbacks are allowed only for allow-listed hosts. Current allow-list:
  `ops.meridian-logistics.example`.
- `http` callbacks are allowed only for loopback hosts (`127.0.0.1`,
  `localhost`, `::1`) for local development.
- Callback URLs containing user-info (`user@host` or `user:pass@host`) are
  rejected.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-7e06b1d4a5c92f38"
```
