# Inventory SKU count endpoint

## Endpoint

- Method: `GET`
- Path: `/api/inventory/count`
- Authentication: ****** required (same as other inventory endpoints)

## Success response

- Status: `200 OK`
- Body:

```json
{"sku_count": 6}
```

`sku_count` is the number of distinct SKU entries in the inventory store.
