# v0.1 acceptance specification

Target user: a developer changing an AI gateway or backend. Journey: run a direct/gateway comparison, inspect the first contract divergence, reproduce the case, repair the gateway, and optionally probe one real endpoint capability.

The representative failure is duplicate rerank documents losing their original identities because a gateway uses text lookup to reconstruct indices. Both duplicates map to the first source position. Recovery preserves original positions, producing a passing rerun. Unicode corruption from decoding individual network chunks is a second representative failure.

Acceptance requires:

1. At least 40 named predeclared synthetic cases. Correct direct and repaired routes pass. Every declared fault seed is detected, and unexpected failures are counted separately.
2. Incremental Unicode/SSE assembly is invariant across byte boundaries; invalid encoding, error events, truncation and cancellation never become success.
3. Rerank source positions, cardinality, scores and optional document echoes satisfy the documented narrow contract. Model score scales and wording are not assumed equal.
4. Quality is reported separately using labelled source-index relevance, with corpus size and explicit synthetic-data limits.
5. Reports preserve reproduction details, safely render hostile text, identify synthetic/live mode and remain usable by keyboard and on small screens.
6. An ordinary real HTTP adapter is exercised on an available model runtime. Untested capabilities remain explicit. Model/runtime/repeats/environment are recorded.
7. Clean checkout and package installation, checks, CI, independent source review and independent acceptance cover the final release commit and tested artifact digests.

This product does not execute business workflows, write to production systems, choose a production migration or certify all providers. It does not distribute model weights. Its distinctive scope is incident-derived Unicode/streaming/source-index diagnostics across the direct/gateway boundary.
