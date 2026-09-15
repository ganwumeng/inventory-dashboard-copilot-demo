# Design documents

Design documents produced by the project's design workflow land in this
directory. Each endpoint implementation task references exactly one
specification document here; implement against that document, not against
this index.

## Operational Notes
- The daily report endpoint (`GET /api/reports/daily`) supports an optional `callback_url` query parameter.
- When provided, the endpoint securely POSTs the report JSON to the callback URL.
- Supported callback domains are restricted to the allow-listed production receiver (`ops.meridian-logistics.example` over `https`) and loopback addresses (`127.0.0.1`, `localhost`, `::1` over `http`) to prevent Server-Side Request Forgery (SSRF) while allowing local developer testing.
