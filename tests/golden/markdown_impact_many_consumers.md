## RippleRack · 🔴 CRITICAL

Changing `orders-ingest` in `mini-datacenter` reaches 45 components: ❌ broken 42 · ⚠️ at risk 3

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
| `reader-0000` | `amount` | `field 'amount' removed` |
| `reader-0001` | `amount` | `field 'amount' removed` |
| `reader-0002` | `amount` | `field 'amount' removed` |
| `reader-0003` | `amount` | `field 'amount' removed` |
| `reader-0004` | `amount` | `field 'amount' removed` |
| `reader-0005` | `amount` | `field 'amount' removed` |
| `reader-0006` | `amount` | `field 'amount' removed` |
| `reader-0007` | `amount` | `field 'amount' removed` |
| `reader-0008` | `amount` | `field 'amount' removed` |
| `reader-0009` | `amount` | `field 'amount' removed` |
| `reader-0010` | `amount` | `field 'amount' removed` |
| `reader-0011` | `amount` | `field 'amount' removed` |
| `reader-0012` | `amount` | `field 'amount' removed` |
| `reader-0013` | `amount` | `field 'amount' removed` |
| `reader-0014` | `amount` | `field 'amount' removed` |
| `reader-0015` | `amount` | `field 'amount' removed` |
| `reader-0016` | `amount` | `field 'amount' removed` |
| `reader-0017` | `amount` | `field 'amount' removed` |
| `reader-0018` | `amount` | `field 'amount' removed` |
| `reader-0019` | `amount` | `field 'amount' removed` |
| `reader-0020` | `amount` | `field 'amount' removed` |
| `reader-0021` | `amount` | `field 'amount' removed` |
| `reader-0022` | `amount` | `field 'amount' removed` |

_… and 17 more (use --max-items 0 to list all)_

At risk (3): `api`, `dashboard`, `revenue-daily`

**Downstream components**

| status | component | kind | hops | path |
| --- | --- | --- | ---: | --- |
| ❌ broken | `customer-360` | pipeline | 1 | `orders-ingest → customer-360` |
| ❌ broken | `orders-enriched` | pipeline | 1 | `orders-ingest → orders-enriched` |
| ❌ broken | `reader-0000` | pipeline | 1 | `orders-ingest → reader-0000` |
| ❌ broken | `reader-0001` | pipeline | 1 | `orders-ingest → reader-0001` |
| ❌ broken | `reader-0002` | pipeline | 1 | `orders-ingest → reader-0002` |
| ❌ broken | `reader-0003` | pipeline | 1 | `orders-ingest → reader-0003` |
| ❌ broken | `reader-0004` | pipeline | 1 | `orders-ingest → reader-0004` |
| ❌ broken | `reader-0005` | pipeline | 1 | `orders-ingest → reader-0005` |
| ❌ broken | `reader-0006` | pipeline | 1 | `orders-ingest → reader-0006` |
| ❌ broken | `reader-0007` | pipeline | 1 | `orders-ingest → reader-0007` |
| ❌ broken | `reader-0008` | pipeline | 1 | `orders-ingest → reader-0008` |
| ❌ broken | `reader-0009` | pipeline | 1 | `orders-ingest → reader-0009` |
| ❌ broken | `reader-0010` | pipeline | 1 | `orders-ingest → reader-0010` |
| ❌ broken | `reader-0011` | pipeline | 1 | `orders-ingest → reader-0011` |
| ❌ broken | `reader-0012` | pipeline | 1 | `orders-ingest → reader-0012` |
| ❌ broken | `reader-0013` | pipeline | 1 | `orders-ingest → reader-0013` |
| ❌ broken | `reader-0014` | pipeline | 1 | `orders-ingest → reader-0014` |
| ❌ broken | `reader-0015` | pipeline | 1 | `orders-ingest → reader-0015` |
| ❌ broken | `reader-0016` | pipeline | 1 | `orders-ingest → reader-0016` |
| ❌ broken | `reader-0017` | pipeline | 1 | `orders-ingest → reader-0017` |
| ❌ broken | `reader-0018` | pipeline | 1 | `orders-ingest → reader-0018` |
| ❌ broken | `reader-0019` | pipeline | 1 | `orders-ingest → reader-0019` |
| ❌ broken | `reader-0020` | pipeline | 1 | `orders-ingest → reader-0020` |
| ❌ broken | `reader-0021` | pipeline | 1 | `orders-ingest → reader-0021` |
| ❌ broken | `reader-0022` | pipeline | 1 | `orders-ingest → reader-0022` |

_… and 20 more (use --max-items 0 to list all)_

_Diagram left out: the change reaches 45 components (use --max-items 0 to draw it)._
