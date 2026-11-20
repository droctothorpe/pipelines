# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Init-only adapter to Argo's installed artifact downloader (standard library only)."""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 'kfp-argo/v1'
DATA_ROOT = '/tmp/kfp/artifact-lists'


def records(value, depth=0):
    if depth > 64:
        raise ValueError('Artifact collection nesting exceeds 64 levels.')
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, list):
        return [record for item in value for record in records(item, depth + 1)]
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise ValueError('Invalid native artifact identity in collection.')
    if not isinstance(value.get('uri'), str) or (
        'metadata' in value and not isinstance(value['metadata'], dict)
    ):
        raise ValueError(
            'Artifact collection requires a URI and valid metadata.'
        )
    if not isinstance(value.get('producer'), dict) or not all(
        isinstance(value['producer'].get(key), str)
        for key in ('run', 'task', 'namespace')
    ):
        raise ValueError('Artifact collection requires producer identity.')
    return [value]


def location(uri, repository):
    parsed = urlsplit(uri)
    if (
        not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(
            'Invalid artifact URI; credentials must not be embedded in the URI.'
        )
    if parsed.scheme in ('s3', 'gs'):
        if parsed.query:
            raise ValueError(
                'Object-storage artifact URIs cannot contain a query.'
            )
        driver = 's3' if parsed.scheme == 's3' else 'gcs'
        config = copy.deepcopy(repository.get(driver, {}))
        if driver == 's3' and not config:
            raise ValueError(
                'S3 artifact-list staging requires a configured S3 repository.'
            )
        config.pop('keyFormat', None)
        config['bucket'] = parsed.netloc
        config['key'] = parsed.path.lstrip('/')
        return {driver: config}
    if parsed.scheme in ('http', 'https'):
        return {'http': {'url': uri}}
    raise ValueError(
        'Artifact-list staging supports S3, GCS and HTTP(S) sources.'
    )


def prepare(parameters, ports, repository):
    values = {entry['name']: entry['value'] for entry in parameters}
    artifacts = []
    manifest = {'schema': SCHEMA, 'inputs': {}, 'singles': []}
    number = 0
    for port, declaration in ports.items():
        kind = (
            declaration if isinstance(declaration, str) else declaration['type']
        )
        single = isinstance(declaration, dict) and declaration.get('single')
        items = records(values['kfp-meta-' + port])
        if single:
            if len(items) != 1:
                raise ValueError(
                    'Artifact iteration must supply exactly one artifact per task.'
                )
            manifest['singles'].append(port)
        staged = []
        for item in items:
            if item.get('type') != kind and kind != 'system.Artifact@0.0.1':
                raise ValueError(
                    f'Artifact type mismatch for collection {port!r}.'
                )
            name = 'artifact-' + str(number)
            entry = {'identity': item, 'path': DATA_ROOT + '/' + name}
            if 'metadata' not in item:
                metadata_uri = item.get('metadataUri')
                if metadata_uri is None:
                    # Earlier native cache entries used canonical payload locations.
                    suffix = '/' + '/'.join(
                        [
                            item['producer']['run'],
                            item['producer']['task'],
                            item['port'],
                        ]
                    )
                    if not item['uri'].endswith(suffix):
                        raise ValueError(
                            'Cached artifact lacks its metadata location; regenerate its producer.'
                        )
                    metadata_uri = (
                        item['uri'].rsplit('/', 1)[0]
                        + '/metadata/'
                        + item['port']
                        + '.json'
                    )
                meta_name = 'metadata-' + str(number)
                artifacts.append(
                    {
                        'name': meta_name,
                        'path': '/' + meta_name,
                        'archive': {'none': {}},
                        **location(metadata_uri, repository),
                    }
                )
                entry['metadataPath'] = DATA_ROOT + '/' + meta_name
            artifacts.append(
                {
                    'name': name,
                    'path': '/' + name,
                    'archive': {'none': {}},
                    **location(item['uri'], repository),
                }
            )
            staged.append(entry)
            number += 1
        manifest['inputs'][port] = staged
    # No main-container mounts here: Argo loads into /argo/inputs/artifacts/<name>.
    template = {
        'name': 'kfp-artifact-list-staging',
        'container': {'image': 'unused'},
        'inputs': {'artifacts': artifacts},
    }
    return template, manifest


def expand_raw_arguments(manifest, arguments, summary):
    replacements = {}
    references = []
    for port, entries in manifest['inputs'].items():
        artifacts = []
        for index, entry in enumerate(entries):
            identity = entry['identity']
            metadata = (
                json.loads(Path(entry['metadataPath']).read_text())
                if 'metadataPath' in entry
                else identity
            )
            if any(
                metadata.get(key) != identity.get(key)
                for key in ('schema', 'port', 'type', 'producer', 'uri')
            ):
                raise ValueError(
                    'Artifact metadata identity mismatch during argument staging.'
                )
            title, version = metadata['type'].split('@', 1)
            artifacts.append(
                {
                    'name': metadata['port'],
                    'uri': metadata['uri'],
                    'metadata': metadata['metadata'],
                    'type': {'schemaTitle': title, 'schemaVersion': version},
                    'customPath': entry['path'],
                    'artifactId': '/'.join(
                        [
                            identity['producer']['run'],
                            identity['producer']['task'],
                            identity['port'],
                        ]
                    ),
                }
            )
            references.append(
                {
                    'port': port
                    if port in manifest.get('singles', [])
                    else f'{port}[{index}]',
                    'producer': identity['producer'],
                    'uri': identity['uri'],
                }
            )
        replacements['__KFP_LIST_' + port + '__'] = json.dumps(
            artifacts, allow_nan=False
        )
        if port in manifest.get('singles', []):
            replacements['__KFP_PATH_' + port + '__'] = entries[0]['path']
    expanded = []
    markers = (
        re.compile('|'.join(re.escape(marker) for marker in replacements))
        if replacements
        else None
    )
    for argument in arguments:
        if markers is not None:
            argument = markers.sub(
                lambda match: replacements[match[0]], argument
            )
        if len(argument.encode()) >= 128 * 1024:
            raise ValueError(
                'Artifact-list argument exceeds the process argument limit; use a Python list consumer.'
            )
        expanded.append(argument)
    summary = copy.deepcopy(summary)
    summary['inputs'] = summary.get('inputs', []) + references
    for artifact in summary.get('artifacts', []):
        artifact['inputs'] = summary['inputs']
    return expanded, summary


def main():
    repository = json.loads(os.environ['KFP_STAGING_REPOSITORY'])
    # A native raw artifact avoids process-argument limits for collection metadata.
    parameters = json.loads(
        Path('/tmp/kfp/artifact-list-inputs.json').read_text()
    )
    template, manifest = prepare(
        parameters, json.loads(sys.argv[1]), repository
    )
    destination = Path('/argo/inputs/artifacts')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'manifest.json').write_text(
        json.dumps(manifest, allow_nan=False)
    )
    # Keep Argo's bootstrap/template writes private to this init-container. Never
    # overwrite the real executor's shared template or expose its storage secrets.
    private = Path('/var/run/argo')
    private.mkdir(parents=True, exist_ok=True)
    (private / 'template').write_text(json.dumps(template, allow_nan=False))
    os.environ.pop('ARGO_TEMPLATE', None)
    os.environ['PATH'] = '/kfp-argo-binary:' + os.environ.get('PATH', '')
    result = subprocess.run(['/kfp-argo-binary/argoexec', 'init'], check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
    if '--raw' in sys.argv[2:]:
        arguments = json.loads(
            Path('/tmp/kfp/artifact-list-args.json').read_text()
        )
        summary = json.loads(
            Path('/tmp/kfp/artifact-list-summary.json').read_text()
        )
        arguments, summary = expand_raw_arguments(manifest, arguments, summary)
        (destination / 'args.json').write_text(
            json.dumps(arguments, allow_nan=False)
        )
        (destination / 'metadata.json').write_text(
            json.dumps(summary, allow_nan=False)
        )
        for artifact in summary.get('artifacts', []):
            port = artifact['port']
            (destination / ('metadata-' + port + '.json')).write_text(
                json.dumps(artifact, allow_nan=False)
            )
            identity = {
                key: artifact[key]
                for key in ('schema', 'port', 'type', 'producer', 'uri')
            }
            identity['metadataUri'] = (
                artifact['uri'].rsplit('/', 1)[0]
                + '/metadata/'
                + port
                + '.json'
            )
            (destination / ('identity-' + port + '.json')).write_text(
                json.dumps(identity, allow_nan=False)
            )


if __name__ == '__main__':
    main()
