# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Metric and Markdown artifacts produced the stock way; the browser smokes
read the resulting runs."""

import pytest
from kfp import dsl

from e2e import support


@dsl.component
def evaluate(metrics: dsl.Output[dsl.ClassificationMetrics]):
    metrics.log_confusion_matrix(['negative', 'positive'], [[3, 1], [1, 5]])
    metrics.log_roc_curve([0.0, 0.1, 1.0], [0.0, 0.9, 1.0], [1.0, 0.5, 0.0])


@dsl.pipeline(name='classification-metrics-compatibility')
def classification_pipeline():
    evaluate()


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
def markdown_pipeline():
    report()


@pytest.mark.full
@pytest.mark.parametrize(
    'function, task_name, artifact',
    [
        (classification_pipeline, 'evaluate', 'metrics'),
        (markdown_pipeline, 'report', 'document'),
    ],
    ids=['classification-metrics', 'markdown'],
)
def test_visualization_artifacts_are_recorded(
    client, record, function, task_name, artifact
):
    submitted, done = support.run_pipeline(client, function, timeout=300)
    assert done.state == 'SUCCEEDED', support.failures(done)
    produced = support.task(done, task_name).outputs.artifacts
    assert any(a.artifact_key == artifact for a in produced), produced
    record(run_id=submitted.run_id, pipeline=function.name, state=done.state)
