# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Classification metrics and Markdown artifacts produced the stock way."""

from kfp import dsl


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
