# Route cache local LRU note

This branch fixes only the process-local eviction semantics tracked in issue #23.

- cache hits refresh recency
- expired entries are removed before refresh
- capacity eviction removes the least recently used entry
- distributed/shared cache remains a deployment-time concern and is intentionally not introduced here
