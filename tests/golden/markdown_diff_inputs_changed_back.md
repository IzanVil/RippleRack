## RippleRack · 🟢 LOW

`mini-datacenter` → `mini-datacenter` · 0 added · 0 removed · 3 modified · 0 schema change(s) · 0 broken consumer(s)

<details>
<summary>Components: 0 added · 0 removed · 3 modified</summary>

| change | kind | id | details |
| --- | --- | --- | --- |
| modified | pipeline | `customer-360` | `inputs: orders-ingest: order_id → all fields` |
| modified | pipeline | `orders-enriched` | `inputs: orders-ingest: -coupon_code +amount +currency +customer_id` |
| modified | pipeline | `revenue-daily` | `inputs: -customer-360` |

</details>
