## RippleRack · 🟢 LOW

Changing `orders-ingest` in `mini-datacenter` reaches 5 components.

Schema `orders` `1.2.0` → `1.3.0` · change: minor · suggested version `1.3.0`

**Schema changes**

| level | kind | detail |
| --- | --- | --- |
| minor | `field_added` | `optional field 'channel' added` |

✅ No consumer breaks.

<details>
<summary>Downstream components (5)</summary>

| status | component | kind | hops | path |
| --- | --- | --- | ---: | --- |
| affected | `customer-360` | pipeline | 1 | `orders-ingest → customer-360` |
| affected | `orders-enriched` | pipeline | 1 | `orders-ingest → orders-enriched` |
| affected | `api` | service | 2 | `orders-ingest → customer-360 → api` |
| affected | `revenue-daily` | pipeline | 2 | `orders-ingest → orders-enriched → revenue-daily` |
| affected | `dashboard` | service | 3 | `orders-ingest → orders-enriched → revenue-daily → dashboard` |

</details>

<details>
<summary>Diagram of the impact</summary>

```mermaid
flowchart LR
  %% mini-datacenter
  %% impact of changing orders-ingest: low
  subgraph rack_rack_b["rack-b"]
    subgraph srv_srv_b1["srv-b1"]
      svc_api("api")
      svc_dashboard("dashboard")
    end
  end
  subgraph grp_pipelines["pipelines"]
    pl_orders_ingest{{"orders-ingest<br/>schema 1.2.0"}}
    pl_orders_enriched{{"orders-enriched<br/>schema 1.0.0"}}
    pl_revenue_daily{{"revenue-daily<br/>schema 2.1.0"}}
    pl_customer_360{{"customer-360<br/>schema 0.4.0"}}
  end
  pl_orders_ingest -->|feeds| pl_orders_enriched
  pl_orders_ingest -->|feeds| pl_customer_360
  pl_orders_enriched -->|feeds| pl_revenue_daily
  pl_revenue_daily -->|data| svc_dashboard
  pl_customer_360 -->|data| svc_api
  classDef changed fill:#ede7f6,stroke:#4527a0,stroke-width:4px,color:#311b92
  class pl_orders_ingest changed
  classDef affected fill:#fff9c4,stroke:#f9a825,color:#5d4037
  class svc_api,svc_dashboard,pl_orders_enriched,pl_revenue_daily,pl_customer_360 affected
  style srv_srv_b1 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style rack_rack_b fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
  linkStyle 0,1,2,3,4 stroke:#f9a825,stroke-width:2px
```

</details>
