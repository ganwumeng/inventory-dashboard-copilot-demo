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

Example of a scheduled call:

```bash
curl "https://dashboard.internal/api/reports/daily"
```
