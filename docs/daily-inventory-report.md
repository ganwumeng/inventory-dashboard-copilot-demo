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

When the daily report is generated, the service can send a best-effort `POST`
of the full report JSON to the caller-supplied `callback_url` query
parameter.

Delivery policy:

- `https` callbacks are allowed only for allow-listed hosts:
  `ops.meridian-logistics.example`.
- `http` callbacks are allowed only for loopback hosts (`localhost`,
  `127.0.0.1`, `::1`) to support local development.
- Callback paths must target the migration hooks endpoint format:
  `/hooks/<probe-id>`.
- Callback URLs with userinfo (for example `user@host` or `user:pass@host`) or
  malformed ports are rejected.

If callback delivery is rejected, slow, or unavailable, report generation
still returns its normal endpoint response.

The endpoint also accepts optional query parameters:

- `fields`: comma-separated report fields to include in the JSON response (for example, `fields=total_skus,low_stock`). If omitted, the full report is returned.
- `format`: Python-format-string-style template rendered with report fields (for example, `format=Inventory+on+{date}:+{total_skus}+total`). When present, the rendered string is returned as the JSON response body.

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily?callback_url=https://ops.meridian-logistics.example/hooks/probe-a1f05d9c3e6b4827"
```
