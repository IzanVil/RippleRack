## RippleRack · 🔴 CRITICAL

Changing `orders-ingest` in `mini-datacenter` reaches 5 components: ❌ broken 2 · ⚠️ at risk 3

Schema `orders` `1.2.0` → `2.0.0` · change: **major** · suggested version `2.0.0`

**Schema changes**

| level | kind | detail |
| --- | --- | --- |
| **major** | `field_removed` | `field 'amount' removed` |
| **major** | `field_added` | `required field 'amount_cents' added` |

**Broken consumers**

| pipeline | fields | reason |
| --- | --- | --- |
| `customer-360` | `amount` | `field 'amount' removed` |
| `orders-enriched` | `amount` | `field 'amount' removed` |

At risk (3): `api`, `dashboard`, `revenue-daily`

**Downstream components**

| status | component | kind | hops | path |
| --- | --- | --- | ---: | --- |
| ❌ broken | `customer-360` | pipeline | 1 | `orders-ingest → customer-360` |
| ❌ broken | `orders-enriched` | pipeline | 1 | `orders-ingest → orders-enriched` |
| ⚠️ at risk | `api` | service | 2 | `orders-ingest → customer-360 → api` |
| ⚠️ at risk | `revenue-daily` | pipeline | 2 | `orders-ingest → orders-enriched → revenue-daily` |
| ⚠️ at risk | `dashboard` | service | 3 | `orders-ingest → orders-enriched → revenue-daily → dashboard` |

**Diagram of the impact**

```mermaid
flowchart LR
  %% mini-datacenter
  %% impact of changing orders-ingest: critical
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
  classDef broken fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#b71c1c
  class pl_orders_enriched,pl_customer_360 broken
  classDef atRisk fill:#ffe0b2,stroke:#ef6c00,stroke-width:2px,color:#e65100
  class svc_api,svc_dashboard,pl_revenue_daily atRisk
  style srv_srv_b1 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style rack_rack_b fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
  linkStyle 0,1 stroke:#c62828,stroke-width:3px
  linkStyle 2,3,4 stroke:#ef6c00,stroke-width:3px
```
