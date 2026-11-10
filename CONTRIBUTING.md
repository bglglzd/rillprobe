# Contributing

Start with a reproducible fixture and the observable expected invariant. Keep transport correctness separate from semantic quality. Synthetic inputs must contain no private data or credentials.

Use Python 3.11+, install `requirements-dev.txt`, then run the unittest, Ruff and build commands in the README. Include a failing case and recovery evidence for behavior changes. Preserve original document positions even when texts repeat. State endpoint/model/runtime and scope for live observations; do not infer live compatibility from mocks.

Report bugs with the case ID, sanitized command, expected and actual result, runtime version and a redacted JSON report. Review the report before sharing it. Changes to public promises need matching documentation and checks.
