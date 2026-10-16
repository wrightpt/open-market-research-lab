# Portal hosting and beta cost model

Planning estimate, 2026-10-16. No resources have been provisioned. Prices are USD per month before tax; verify the chosen region/SKU before approval. These are synthetic-service budgets, not measured capacity guarantees.

## Workload assumptions

Assume every listed user is active, 50 bounded data calls per day, 30 days per month, and an average 64 KiB response. Agent model inference, real data licensing, research execution, and bulk downloads are excluded. Requests and returned bytes, rather than registrations, drive cost.

| Active users | Calls/month | Response payload/month | Average calls/second |
| ---: | ---: | ---: | ---: |
| 10 | 15,000 | 0.92 GiB | 0.0058 |
| 100 | 150,000 | 9.16 GiB | 0.058 |
| 1,000 | 1,500,000 | 91.55 GiB | 0.579 |

Formula: users × 50 × 30 × 65,536 / 2^30 GiB. Allow overhead for TLS, metadata, static assets, retries and logs. A 20× burst multiplier makes the largest scenario about 12 requests/second. That is a load-test target, not an observed result. A client reaching its full daily quota can consume much more than this baseline.

## Isolated VPS budget

Published DigitalOcean Basic examples are $12 for 1 vCPU/2 GiB, $24 for 2 vCPU/4 GiB, and $48 for 4 vCPU/8 GiB. Weekly VM backups add 20%. Spaces starts at $5 for 250 GiB storage and 1 TiB transfer. Source links are below.

| Users | Suggested test sizing | VM | Weekly VM backup | Separate application backup storage | Estimated total |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10 | 1 vCPU / 2 GiB | $12 | $2.40 | $5 | $19.40 |
| 100 | 2 vCPU / 4 GiB | $24 | $4.80 | $5 | $33.80 |
| 1,000 | 4 vCPU / 8 GiB, subject to load test | $48 | $9.60 | $5 | $62.60 |

Use one application instance and local transactional SQLite only while measured contention and restore tests justify that design. Multiple hosts must not have independent quota databases. Do not share SQLite through a network filesystem to simulate horizontal scaling. A migration to shared transactional authorization/quota storage is a separate tested change.

Budget another $2–$10/month as an allowance for a domain and modest external monitoring; this is a planning allowance, not a vendor quote. No paid identity service is assumed. GitHub-hosted public-repository CI must retain restricted permissions and bounded execution; private CI minutes and future artifact retention may add charges. Operator time, incident response, and security review are excluded.

## Separate Kubernetes comparison

DOKS lists a free standard control plane, worker nodes from $12/month, load balancers from $12/month, and optional highly available control plane at $40/month. A cluster must be separate from production trading infrastructure.

| Users | Worker assumption | Workers | Load balancer | Storage/backup allowance | Base total | With HA control plane |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 10 | 2 × $12 | $24 | $12 | $15 | $51 | $91 |
| 100 | 2 × $24 | $48 | $12 | $15 | $75 | $115 |
| 1,000 | 3 × $24 | $72 | $12 | $15 | $99 | $139 |

The $15 is a budgeting allowance for a persistent volume plus application backups. These totals do not buy an HA database or prove the application can run multiple replicas. With the initial SQLite design, run one stateful application replica; spare worker capacity mainly helps maintenance. Multi-replica authorization, OAuth state, quotas and revocation need shared transactional storage and failure tests before claiming availability.

| Decision | Isolated VPS | Separate Kubernetes environment |
| --- | --- | --- |
| Initial operations | One host, service, TLS proxy and restore procedure | Cluster, ingress, storage, policies, upgrade and restore procedures |
| Isolation from trading | Separate account/project/network; no peering or cluster credentials | Separate cluster/account/network, not merely another trading namespace |
| Failure mode | Single host outage; restore to replacement | Scheduler can replace workloads; state and access ledger still need recovery |
| Scaling | Resize first; migrate shared state before replicas | Replicas only after shared authorization/quota state is implemented |
| Best fit now | Small invitation-only synthetic beta | Later workloads or availability needs that justify the extra operations |

## Smallest safe beta recommendation

After a separate deployment approval, invite ten GitHub users, require explicit access approval, issue short-lived research-only keys, and expose synthetic fixtures only. Start on a separate 2 GiB VPS with HTTPS, one application instance, fixed query ceilings, account-wide quotas and an emergency access-disable path. Verify GitHub login against a staging OAuth app, revocation, restore without resurrecting revoked keys, and actual client compatibility before promising supported clients.

Keep hosted MCP labeled experimental until its exact OAuth and protocol/client matrix passes. REST plus the local stdio adapter provides a smaller initial support surface. No user strategy code runs on the API host. External executable contributions run only in restricted GitHub-hosted CI or separately isolated runners without production credentials.

Measure response latency, database lock waits, quota refusals, concurrent requests, response bytes and disk growth. Add global ingress/body/time/concurrency limits before opening access. Scale from evidence, not the user-count label.

Real datasets have no cost estimate here because redistribution rights, approved fields, retention, data volume and service identity are unapproved. Their licensing, storage and export costs may exceed hosting.

## Sources

Checked 2026-10-16:

- [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets)
- [DigitalOcean backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/)
- [DigitalOcean Spaces pricing](https://www.digitalocean.com/pricing/spaces-object-storage)
- [DigitalOcean Kubernetes pricing](https://www.digitalocean.com/pricing/kubernetes)
- [Database backup caveat](https://docs.digitalocean.com/products/backups/details/limits/): application-consistent backup is necessary for active databases; a VM snapshot alone is insufficient.
