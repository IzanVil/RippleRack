## RippleRack · 🟠 HIGH

`mini-datacenter` → `mini-datacenter` · 2 added · 0 removed · 3 modified · 1 schema change(s) · 1 broken consumer(s)

### 🟠 HIGH · `orders-ingest`

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

At risk (1): `api`

<details>
<summary>Diagram of the impact</summary>

```mermaid
flowchart LR
  %% mini-datacenter
  %% impact of changing orders-ingest: high
  subgraph rack_rack_b["rack-b"]
    subgraph srv_srv_b1["srv-b1"]
      svc_api("api")
      svc_dashboard("dashboard")
    end
  end
  subgraph grp_pipelines["pipelines"]
    pl_orders_ingest{{"orders-ingest<br/>schema 2.0.0"}}
    pl_orders_enriched{{"orders-enriched<br/>schema 1.0.0"}}
    pl_revenue_daily{{"revenue-daily<br/>schema 2.1.0"}}
    pl_customer_360{{"customer-360<br/>schema 0.4.0"}}
    pl_orders_audit{{"orders-audit<br/>schema 0.1.0"}}
  end
  pl_orders_ingest -->|feeds| pl_orders_enriched
  pl_orders_ingest -->|feeds| pl_customer_360
  pl_orders_ingest -->|feeds| pl_orders_audit
  pl_orders_enriched -->|feeds| pl_revenue_daily
  pl_revenue_daily -->|data| svc_dashboard
  pl_customer_360 -->|data| svc_api
  classDef changed fill:#ede7f6,stroke:#4527a0,stroke-width:4px,color:#311b92
  class pl_orders_ingest changed
  classDef broken fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#b71c1c
  class pl_customer_360 broken
  classDef atRisk fill:#ffe0b2,stroke:#ef6c00,stroke-width:2px,color:#e65100
  class svc_api atRisk
  classDef affected fill:#fff9c4,stroke:#f9a825,color:#5d4037
  class svc_dashboard,pl_orders_enriched,pl_revenue_daily,pl_orders_audit affected
  style srv_srv_b1 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style rack_rack_b fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
  linkStyle 1 stroke:#c62828,stroke-width:3px
  linkStyle 5 stroke:#ef6c00,stroke-width:3px
  linkStyle 0,2,3,4 stroke:#f9a825,stroke-width:2px
```

</details>

<details>
<summary>Components: 2 added · 0 removed · 3 modified</summary>

| change | kind | id | details |
| --- | --- | --- | --- |
| added | service | `redis` | on `srv-b1` |
| added | pipeline | `orders-audit` | runs on `postgres` |
| modified | server | `srv-b1` | `memory_gb: 96 → 64` |
| modified | pipeline | `orders-enriched` | `inputs: orders-ingest: -amount +amount_cents` |
| modified | pipeline | `orders-ingest` | `schema.version: 1.2.0 → 2.0.0`<br>`schema.fields: changed (see above)` |

</details>

<details>
<summary>Dependencies: 1 added · 0 removed · 1 modified</summary>

| change | dependency | kind |
| --- | --- | --- |
| added | `api → redis` | runtime |
| modified | `spark → kafka` | network → data |

</details>
