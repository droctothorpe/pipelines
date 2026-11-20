# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""An importer inside a nested pipeline: the UI must expand the ancestors of a
deep-linked task and explain that importers have no execution pod."""

from kfp import dsl

README = (
    'https://raw.githubusercontent.com/kubeflow/pipelines/'
    '7780f12acfbde9f16169c7fcbfdfb6c3ef5432ea/README.md'
)


@dsl.component
def check(data: dsl.Input[dsl.Dataset]) -> int:
    from pathlib import Path

    text = Path(data.path).read_text()
    assert 'Kubeflow' in text
    return len(text)


@dsl.pipeline(name='nested-importer-inner')
def inner(uri: str) -> int:
    imported = dsl.importer(
        artifact_uri=uri,
        artifact_class=dsl.Dataset,
        metadata={'origin': 'public-http'},
    )
    return check(data=imported.output).output


@dsl.pipeline(name='nested-importer-ui')
def pipeline(uri: str = README):
    inner(uri=uri)
