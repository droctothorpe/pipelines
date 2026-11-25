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

![remote image, fetched as in stock](https://tracker.invalid/pixel)

<script>window.__unexpectedMarkdownExecution = true</script>
""")


@dsl.pipeline(name='markdown-viewer-compatibility')
def markdown_pipeline():
    report()


@dsl.component
def summarize(
    mlpipeline_ui_metadata: dsl.Output[dsl.Artifact],
    table: dsl.Output[dsl.Artifact],
):
    """Stock's legacy viewer contract: declare viewers in an output artifact
    named mlpipeline-ui-metadata, with inline sources or this task's own
    artifact URIs."""
    import json
    from pathlib import Path

    Path(table.path).write_text('baseline,0.81\ntuned,0.94\n')
    Path(mlpipeline_ui_metadata.path).write_text(
        json.dumps(
            {
                'outputs': [
                    {
                        'type': 'table',
                        'format': 'csv',
                        'header': ['model', 'accuracy'],
                        'source': table.uri,
                    },
                    {
                        'type': 'confusion_matrix',
                        'format': 'csv',
                        'schema': [
                            {'name': 'target', 'type': 'CATEGORY'},
                            {'name': 'predicted', 'type': 'CATEGORY'},
                            {'name': 'count', 'type': 'NUMBER'},
                        ],
                        'labels': ['negative', 'positive'],
                        'storage': 'inline',
                        'source': 'negative,negative,3\nnegative,positive,1\n'
                        'positive,negative,1\npositive,positive,5\n',
                    },
                    {
                        'type': 'roc',
                        'format': 'csv',
                        'schema': [
                            {'name': 'fpr', 'type': 'NUMBER'},
                            {'name': 'tpr', 'type': 'NUMBER'},
                            {'name': 'thresholds', 'type': 'NUMBER'},
                        ],
                        'storage': 'inline',
                        'source': '0.0,0.0,1.0\n0.1,0.9,0.5\n1.0,1.0,0.0\n',
                    },
                    {
                        'type': 'markdown',
                        'storage': 'inline',
                        'source': '## Legacy summary\n\nThe tuned model **wins**.',
                    },
                    {
                        'type': 'web-app',
                        'storage': 'inline',
                        'source': '<h1>Legacy web app</h1><script>document.title="x"</script>',
                    },
                    {
                        'type': 'tensorboard',
                        'source': table.uri.rsplit('/', 1)[0] + '/logs',
                    },
                ]
            }
        )
    )


@dsl.pipeline(name='legacy-ui-metadata-compatibility')
def ui_metadata_pipeline():
    summarize()
