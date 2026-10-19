## RippleRack · 🟠 HIGH

`mini-datacenter` → `mini-datacenter` · 0 added · 0 removed · 2 modified · 1 schema change(s) · 41 broken consumer(s)

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
| `reader-0023` | `amount` | `field 'amount' removed` |

_… and 16 more (use --max-items 0 to list all)_

At risk (1): `api`

_Diagram left out: the change reaches 45 components (use --max-items 0 to draw it)._

<details>
<summary>Components: 0 added · 0 removed · 2 modified</summary>

| change | kind | id | details |
| --- | --- | --- | --- |
| modified | pipeline | `orders-enriched` | `inputs: orders-ingest: -amount +amount_cents` |
| modified | pipeline | `orders-ingest` | `schema.version: 1.2.0 → 2.0.0`<br>`schema.fields: changed (see above)` |

</details>
