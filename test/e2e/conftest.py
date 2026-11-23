# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Live end-to-end suite for the native stack.

Every test here drives the public ``kfp`` client against a deployed native
installation named by ``KFP_TEST_HOST``, ``KFP_TEST_NAMESPACE`` and
``KFP_TEST_TOKEN``. Without ``KFP_TEST_HOST`` the whole package is skipped, so
the offline suite is unaffected.

Tiers are pytest markers. ``test/native-deployment.sh`` runs everything but
``prerequisite`` on every pull request, in parallel with pytest-xdist grouped
by module; ``smoke`` is the quick representative subset for a local check;
``full`` is the rest; ``prerequisite`` needs hardware or credentials a local
cluster may lack and skips with a reason. ``no_cluster`` marks the few tests
that need no deployment.

Optional settings: ``KFP_TEST_IMAGE`` (a prebuilt image carrying this SDK, used
by components that would otherwise install KFP from PyPI), ``KFP_TEST_CONTEXT``
(a kubeconfig context for the direct-Kubernetes authentication test, and
KFP_TEST_ARGO_SERVER for its archive reads straight from Argo Server),
``KFP_TEST_ARTIFACT_ROOT`` (an alternative object-store root), and
``--e2e-output`` (where the JSON report and compiled manifests are written).
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

TIERS = {
    'smoke': 'runs on every pull request against a disposable cluster',
    'full': 'broader coverage for nightly or on-demand runs',
    'prerequisite': 'needs hardware or credentials this cluster may lack',
    'no_cluster': 'does not need a deployed installation',
}


@dataclass(frozen=True)
class Settings:
    host: str
    namespace: str
    token: str
    output: Path
    image: str | None
    context: str | None
    argo_server: str | None
    artifact_root: str


def pytest_addoption(parser):
    parser.addoption(
        '--e2e-output',
        default=None,
        help='Directory for the end-to-end JSON report and compiled manifests.',
    )


def pytest_configure(config):
    for marker, text in TIERS.items():
        config.addinivalue_line('markers', f'{marker}: {text}')
    # Fix the output directory once on the controller so xdist workers, which
    # inherit the environment, share it instead of each choosing a timestamp.
    if 'PYTEST_XDIST_WORKER' not in os.environ and not os.environ.get(
        'KFP_TEST_OUTPUT'
    ):
        os.environ['KFP_TEST_OUTPUT'] = config.getoption(
            '--e2e-output'
        ) or '/tmp/kfp-e2e-' + datetime.now(timezone.utc).strftime(
            '%Y%m%d-%H%M%S'
        )


def pytest_sessionfinish(session, exitstatus):
    """Merge per-worker reports into one report.json on the controller."""
    if 'PYTEST_XDIST_WORKER' in os.environ:
        return
    output = os.environ.get('KFP_TEST_OUTPUT')
    if not output or not Path(output).is_dir():
        return
    entries = []
    for part in sorted(Path(output).glob('report-*.json')):
        entries.extend(json.loads(part.read_text()))
        part.unlink()
    if entries:
        (Path(output) / 'report.json').write_text(
            json.dumps(entries, indent=2, default=str)
        )


def pytest_collection_modifyitems(config, items):
    if os.environ.get('KFP_TEST_HOST'):
        return
    skip = pytest.mark.skip(
        reason='KFP_TEST_HOST is not set; the live suite needs a deployed native installation.'
    )
    here = Path(__file__).parent
    for item in items:
        if not Path(str(item.fspath)).is_relative_to(here):
            continue
        if item.get_closest_marker('no_cluster') is None:
            item.add_marker(skip)


@pytest.fixture(scope='session')
def settings(request):
    token = os.environ.get('KFP_TEST_TOKEN', '')
    if not token:
        pytest.skip('KFP_TEST_TOKEN must be non-empty for the live suite.')
    output = Path(os.environ['KFP_TEST_OUTPUT'])
    output.mkdir(parents=True, exist_ok=True)
    return Settings(
        host=os.environ['KFP_TEST_HOST'],
        namespace=os.environ.get('KFP_TEST_NAMESPACE', 'kfp-argo'),
        token=token,
        output=output,
        image=os.environ.get('KFP_TEST_IMAGE') or None,
        context=os.environ.get('KFP_TEST_CONTEXT') or None,
        argo_server=os.environ.get('KFP_TEST_ARGO_SERVER') or None,
        artifact_root=os.environ.get(
            'KFP_TEST_ARTIFACT_ROOT', 's3://argo-artifacts'
        ).rstrip('/'),
    )


@pytest.fixture(scope='session')
def client(settings):
    import kfp

    from e2e import support

    return support.as_user(
        kfp.Client(
            host=settings.host,
            namespace=settings.namespace,
            existing_token=settings.token,
        )
    )


@pytest.fixture(scope='session')
def namespace(settings):
    return settings.namespace


@pytest.fixture(scope='session')
def report(settings):
    """Entries recorded by tests, written as one JSON report per session."""
    entries = []
    yield entries
    worker = os.environ.get('PYTEST_XDIST_WORKER', 'main')
    (settings.output / f'report-{worker}.json').write_text(
        json.dumps(entries, indent=2, default=str)
    )


@pytest.fixture
def record(report, request):
    def add(**fields):
        report.append({'test': request.node.nodeid, **fields})

    return add
