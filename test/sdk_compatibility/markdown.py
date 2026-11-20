# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Produce a Markdown artifact for the authenticated viewer security smoke."""

import json
import os
from uuid import uuid4

import kfp
from kfp import dsl


@dsl.component
def report(document: dsl.Output[dsl.Markdown]):
    from pathlib import Path

    Path(document.path).write_text("""# Evaluation report

**Passed**: all semantic checks completed.

| Metric | Value |
| --- | --- |
| Accuracy | 0.94 |

- Files downloaded
- Metadata preserved

```python
assert score > 0.9
```

![remote tracking image](https://tracker.invalid/pixel)

<script>window.__unexpectedMarkdownExecution = true</script>
""")


@dsl.pipeline(name='markdown-viewer-compatibility')
def pipeline():
    report()


if __name__ == '__main__':
    namespace = os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo')
    client = kfp.Client(
        host=os.environ.get('KFP_TEST_HOST', 'http://127.0.0.1:3003'),
        namespace=namespace,
        existing_token=os.environ['KFP_TEST_TOKEN'],
    )
    run = client.create_run_from_pipeline_func(
        pipeline,
        arguments={},
        run_name='Markdown compatibility ' + uuid4().hex[:8],
        experiment_name='SDK backwards compatibility',
        namespace=namespace,
    )
    done = run.wait_for_run_completion(timeout=180)
    assert done.state == 'SUCCEEDED', done.state
    print(json.dumps({'run_id': run.run_id}))
