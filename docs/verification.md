# Verification scope

This document describes the v0.1 workload and limits. Release evidence is bound to the release commit and published package digests in the release manifest; development observations alone are not a release pass.

## Deterministic workload

51 predeclared synthetic fixtures, two loopback HTTP routes each. Correct direct and repaired gateway routes pass 102/102 checks. The broken gateway produces eight expected failures and no other failures on this workload. The eight seeds are defined in `rillprobe/fixtures.py`; the test suite requires every one to be detected. These are measured results on a fixed authored set, not a false-positive guarantee on all providers.

Retrieval demonstration: five authored queries, twenty short synthetic documents, relevance grades 0–3. A simple lexical baseline supplies rankings. The report computes MRR and nDCG independently from those scores. No held-out or real retrieval-quality evaluation is claimed. Texts are original synthetic fixtures, distributed under the project MIT license.

## Real route

The separately installed development wheel exercised a real CPU llama.cpp server with Qwen2.5-0.5B-Instruct Q4_K_M on 2026-11-10. Three repeated chat requests passed the strict streaming contract and reported the configured model ID. Runtime: llama.cpp 0.9.0-dev, build 12211, commit 7d7f02875. The task-owned Linux x86_64 container was limited to two CPUs and 2 GiB RAM, with no GPU. Observed request durations were 1.019, 0.601 and 0.670 seconds for the fixed short prompt; this is a tiny transport smoke, not a model-performance benchmark. All three generated texts happened to match; wording equality was not an acceptance rule. No paid API was used.

The model came from the official [Qwen GGUF repository](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/tree/9217f5db79a29953eb74d5343926648285ec7e67), revision 9217f5db79a29953eb74d5343926648285ec7e67, file qwen2.5-0.5b-instruct-q4_k_m.gguf, SHA256 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db, licensed Apache-2.0. The model and runtime are not bundled. The release repeats the package integration on the frozen source and binds the accepted package digest in its manifest; earlier development observations do not automatically transfer to a changed artifact.

No live reranking endpoint or live tool-call generation has been verified. Their deterministic contract behavior is covered in synthetic fixtures. Model answer quality, paid-provider billing and all-version gateway compatibility remain outside the verified scope. No service endpoints, infrastructure identifiers or credentials from the private build environment are published here.

## Reproduce

Run the README commands in a clean environment. A broken demo exits 1; a repaired demo exits 0. Inspect JSON case IDs and actual errors, not only the totals. The package has no runtime dependencies; build and lint tools are pinned separately. Performance varies by machine and is reported with environment and workload in each run. Release notes should provide measured duration and machine context without treating that number as a universal benchmark.
