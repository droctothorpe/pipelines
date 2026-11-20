# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Native resource operations behind the existing public Client facade.

The method names match the facade's internal service calls, not HTTP
endpoints. Only Kubernetes and Argo APIs are contacted.
"""

import copy
import datetime
import hashlib
import json
import re
import warnings
from urllib.parse import quote
from uuid import uuid4

from kfp import server_api as models
from kfp.client._listing import page
from kfp.client._pipeline_package import extract_pipeline, override_caching
from kfp.client._scheduling import (
    SCHEDULE_CONFIG,
    cron_schedule,
    trigger_from_config,
)
from kfp.client._scheduling import (
    settings as schedule_settings,
)
from kfp.client._transport import NativeTransport
from kfp.compiler.argo_artifacts import ROOT_KEYS, override_root
from kfp.dsl.argo_runtime import deserialize, serialize

RESOURCE = 'pipelines.kubeflow.org/resource'
PIPELINE = 'pipelines.kubeflow.org/pipeline'
EXPERIMENT = 'pipelines.kubeflow.org/experiment'
DISPLAY_NAME = 'pipelines.kubeflow.org/display-name'
DESCRIPTION = 'pipelines.kubeflow.org/description'
VERSION_ID = 'pipelines.kubeflow.org/version-id'
TEMPLATE = 'pipelines.kubeflow.org/workflow-template'
PARAMETER_TYPES = 'pipelines.kubeflow.org/parameter-types'


def timestamp(value):
    return (
        datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value
        else None
    )


def segment(value):
    return quote(str(value), safe='')


def not_found(resource, identity):
    return models.ApiException(
        status=404, reason=f'{resource} {identity!r} was not found.'
    )


class NativeBackend:
    def __init__(
        self,
        configuration,
        namespace,
        cookies=None,
        header_name=None,
        header_value=None,
    ):
        self.transport = NativeTransport(
            configuration, cookies, header_name, header_value
        )
        self._user_namespace = namespace
        self._known_namespaces = {}
        self._known_workflows = {}
        self._archive_warned = False

    def _namespace(self, namespace=None):
        return (
            namespace
            or self._user_namespace()
            or self.transport.request('GET', '/argo/api/v1/info').get(
                'managedNamespace'
            )
            or 'kubeflow'
        )

    def _maps_path(self, namespace):
        return f'/kubernetes/api/v1/namespaces/{segment(namespace)}/configmaps'

    def _maps(self, kind, namespace):
        return self.transport.collection(
            self._maps_path(namespace),
            params={'labelSelector': f'{RESOURCE}={kind}'},
            kubernetes=True,
        )

    def _remember(self, resource):
        metadata = resource['metadata']
        if metadata.get('uid') and metadata.get('namespace'):
            self._known_namespaces[metadata['uid']] = metadata['namespace']
        return resource

    def _find_map(self, kind, identity, namespace=None):
        namespace = (
            namespace
            or self._known_namespaces.get(identity)
            or self._namespace()
        )
        for item in self._maps(kind, namespace):
            if item['metadata'].get('uid') == identity:
                return self._remember(item)
        raise not_found(kind, identity)

    def _delete_map(self, resource):
        metadata = resource['metadata']
        if not metadata.get('uid'):
            raise models.ApiException(
                status=409,
                reason='Refresh the resource before deleting it; its UID is missing.',
            )
        self.transport.request(
            'DELETE',
            self._maps_path(metadata['namespace'])
            + '/'
            + segment(metadata['name']),
            body={
                'apiVersion': 'v1',
                'kind': 'DeleteOptions',
                'preconditions': {'uid': metadata['uid']},
            },
        )
        return {}

    def _page(self, model, field, values, scope, **options):
        values, total, token = page(values, scope=scope, **options)
        return model(
            **{field: values, 'total_size': total, 'next_page_token': token}
        )

    def healthz_service_get_healthz(self):
        self.transport.request('GET', '/argo/api/v1/info')
        return models.V2GetHealthzResponse(
            multi_user=True, pipeline_store='kubernetes'
        )

    def _experiment(self, resource, latest_runs=None):
        self._remember(resource)
        metadata, data = resource['metadata'], resource.get('data', {})
        latest = latest_runs or {}
        return models.V2Experiment(
            experiment_id=metadata['uid'],
            display_name=data.get('displayName', metadata['name']),
            description=data.get('description'),
            namespace=metadata.get('namespace'),
            created_at=timestamp(metadata.get('creationTimestamp')),
            storage_state=data.get('storageState', 'AVAILABLE'),
            last_run_created_at=latest.get(metadata['uid'])
            or latest.get(metadata['name']),
        )

    def _latest_runs(self, namespace):
        """Most recent workflow creation per experiment, live and archived.

        Enrichment only: an experiment stays readable when its namespace's run
        inventory cannot be listed (for example archive access, C18).
        """
        latest = {}
        try:
            runs = self._workflow_resources(
                namespace, tolerate_archive=True
            ).values()
        except models.ApiException:
            return latest
        for run in runs:
            experiment = run['metadata'].get('labels', {}).get(EXPERIMENT)
            created = timestamp(run['metadata'].get('creationTimestamp'))
            if (
                experiment
                and created
                and (experiment not in latest or created > latest[experiment])
            ):
                latest[experiment] = created
        return latest

    def experiment_service_create_experiment(self, experiment):
        namespace = self._namespace(experiment.namespace)
        resource = {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {
                'name': 'experiment-' + str(uuid4()),
                'namespace': namespace,
                'labels': {RESOURCE: 'experiment'},
            },
            'data': {
                'displayName': experiment.display_name,
                'description': experiment.description or '',
                'storageState': 'AVAILABLE',
            },
        }
        return self._experiment(
            self.transport.request(
                'POST', self._maps_path(namespace), body=resource
            )
        )

    def experiment_service_list_experiments(
        self,
        page_token='',
        page_size=10,
        sort_by='',
        namespace=None,
        filter=None,
    ):
        namespace = self._namespace(namespace)
        latest = self._latest_runs(namespace)
        values = [
            self._experiment(item, latest)
            for item in self._maps('experiment', namespace)
        ]
        return self._page(
            models.V2ListExperimentsResponse,
            'experiments',
            values,
            ['experiments', namespace],
            page_token=page_token,
            page_size=page_size,
            sort_by=sort_by,
            filter=filter,
        )

    def experiment_service_get_experiment(self, experiment_id):
        resource = self._find_map('experiment', experiment_id)
        return self._experiment(
            resource, self._latest_runs(resource['metadata']['namespace'])
        )

    def _experiment_storage(self, experiment_id, state):
        resource = self._find_map('experiment', experiment_id)
        metadata = resource['metadata']
        if state == 'ARCHIVED':
            namespace = metadata['namespace']
            identities = {metadata['uid'], metadata['name']}
            # Enumerate first, so an authorization/list failure changes nothing.
            schedules = [
                schedule
                for schedule in self._schedules(namespace)
                if schedule['metadata'].get('namespace') == namespace
                and schedule.get('spec', {})
                .get('workflowMetadata', {})
                .get('labels', {})
                .get(EXPERIMENT)
                in identities
            ]

            def associated_runs():
                return [
                    run
                    for run in self._workflow_resources(namespace).values()
                    if run['metadata'].get('namespace') == namespace
                    and run['metadata'].get('labels', {}).get(EXPERIMENT)
                    in identities
                ]

            runs = associated_runs()
            for schedule in schedules:
                try:
                    self._set_schedule_suspended(schedule, True)
                except models.ApiException as error:
                    if error.status != 404:
                        raise
            if schedules:
                # Include runs created while suspension requests were in flight.
                runs = associated_runs()
            for run in runs:
                self._set_run_storage(run, 'ARCHIVED')
        # Publish the experiment state last. Partial failures remain retryable;
        # restoring an experiment deliberately leaves its children unchanged.
        resource.setdefault('data', {})['storageState'] = state
        self.transport.request(
            'PUT',
            self._maps_path(metadata['namespace'])
            + '/'
            + segment(metadata['name']),
            body=resource,
        )
        return {}

    def experiment_service_archive_experiment(self, experiment_id):
        return self._experiment_storage(experiment_id, 'ARCHIVED')

    def experiment_service_unarchive_experiment(self, experiment_id):
        return self._experiment_storage(experiment_id, 'AVAILABLE')

    def experiment_service_delete_experiment(self, experiment_id):
        return self._delete_map(self._find_map('experiment', experiment_id))

    def _workflow_spec(self, run, enable_caching=None, cache_key=None):
        if run.pipeline_spec:
            manifest = copy.deepcopy(run.pipeline_spec)
        elif run.pipeline_version_reference:
            reference = run.pipeline_version_reference
            version = self.pipeline_service_get_pipeline_version(
                reference.pipeline_id, reference.pipeline_version_id
            )
            manifest = copy.deepcopy(version.pipeline_spec)
        else:
            raise models.ApiException(
                status=400, reason='A pipeline package or version is required.'
            )
        if enable_caching is not None or cache_key is not None:
            override_caching(manifest, enable_caching, cache_key)
        if run.runtime_config and run.runtime_config.pipeline_root:
            override_root(manifest, run.runtime_config.pipeline_root)
        annotations = manifest.get('metadata', {}).get('annotations', {})
        spec = copy.deepcopy(manifest['spec'])
        if manifest['kind'] == 'CronWorkflow':
            spec = spec['workflowSpec']
        # Pipeline labels and run annotations belong to the run, not to an embedded
        # template's defaults. Removing these defaults does not change task execution.
        spec.pop('workflowMetadata', None)
        supplied = (
            (run.runtime_config.parameters or {}) if run.runtime_config else {}
        )
        definitions = {
            parameter['name']: parameter
            for parameter in spec.get('arguments', {}).get('parameters', [])
        }
        unknown = set(supplied) - definitions.keys()
        if unknown:
            raise models.ApiException(
                status=400,
                reason=f'Unknown pipeline parameters: {sorted(unknown)}',
            )
        kinds = json.loads(
            annotations.get('pipelines.kubeflow.org/parameter-types', '{}')
        )
        parameters = {}
        for name, declaration in definitions.items():
            kind = kinds.get(name, 'String')
            if name in supplied:
                value = supplied[name]
            elif 'value' in declaration:
                value = deserialize(str(declaration['value']), kind)
            else:
                raise models.ApiException(
                    status=400, reason=f'Missing required parameter: {name}'
                )
            try:
                declaration['value'] = serialize(value, kind)
            except (ValueError, TypeError) as error:
                raise models.ApiException(
                    status=400, reason=str(error)
                ) from error
            parameters[name] = value
        if run.service_account:
            spec['serviceAccountName'] = run.service_account
        if run.plugins_input:
            raise NotImplementedError(
                'Backend plugin inputs require a native plugin implementation; they cannot be silently ignored.'
            )
        return manifest, spec, parameters

    def _prepare_staging(self, spec, namespace):
        from kfp.client._artifact_repository import prepare_staging

        prepare_staging(
            spec,
            lambda name: self.transport.request(
                'GET', self._maps_path(namespace) + '/' + segment(name)
            ),
        )

    def _run(self, resource, storage_state='AVAILABLE', pod_uids=None):
        from kfp.client._task_details import tasks

        details = tasks(resource, pod_uids)
        self._remember(resource)
        metadata = resource['metadata']
        if (
            metadata.get('uid')
            and metadata.get('namespace')
            and metadata.get('name')
        ):
            self._known_workflows[metadata['uid']] = (
                metadata['namespace'],
                metadata['name'],
            )
        metadata, spec, status = (
            resource['metadata'],
            resource.get('spec', {}),
            resource.get('status', {}),
        )
        labels, annotations = (
            metadata.get('labels', {}),
            metadata.get('annotations', {}),
        )
        state = {
            'Pending': 'PENDING',
            'Running': 'RUNNING',
            'Succeeded': 'SUCCEEDED',
            'Failed': 'FAILED',
            'Error': 'FAILED',
        }.get(status.get('phase'), 'PENDING')
        if spec.get('shutdown'):
            state = (
                'CANCELING' if state in ('PENDING', 'RUNNING') else 'CANCELED'
            )
        parameters = json.loads(
            annotations.get('pipelines.kubeflow.org/parameters', '{}')
        )
        reference = None
        if labels.get(VERSION_ID):
            reference = models.V2PipelineVersionReference(
                pipeline_id=labels.get(PIPELINE),
                pipeline_version_id=labels[VERSION_ID],
            )
        created = timestamp(metadata.get('creationTimestamp'))
        history = []
        if created:
            history.append(
                models.V2RuntimeStatus(update_time=created, state='PENDING')
            )
        if status.get('startedAt') and state != 'PENDING':
            history.append(
                models.V2RuntimeStatus(
                    update_time=timestamp(status['startedAt']), state='RUNNING'
                )
            )
        if status.get('finishedAt') and state not in ('PENDING', 'RUNNING'):
            history.append(
                models.V2RuntimeStatus(
                    update_time=timestamp(status['finishedAt']), state=state
                )
            )
        return models.V2Run(
            tasks=details,
            task_count=len(details) if details is not None else None,
            run_id=metadata['uid'],
            display_name=annotations.get(DISPLAY_NAME, metadata['name']),
            description=annotations.get(DESCRIPTION),
            namespace=metadata.get('namespace'),
            experiment_id=labels.get(EXPERIMENT),
            state=state,
            state_history=history,
            storage_state=storage_state,
            created_at=created,
            # Argo stamps schedule-created workflows; manual runs are scheduled
            # at creation, as in stock.
            scheduled_at=timestamp(
                annotations.get('workflows.argoproj.io/scheduled-time')
            )
            or created,
            finished_at=timestamp(status.get('finishedAt')),
            runtime_config=models.V2RuntimeConfig(
                parameters=parameters,
                pipeline_root=annotations.get(
                    'pipelines.kubeflow.org/pipeline-root'
                )
                or annotations.get(
                    'pipelines.kubeflow.org/artifact-repository'
                ),
            ),
            service_account=spec.get('serviceAccountName'),
            pipeline_version_id=labels.get(VERSION_ID),
            pipeline_version_reference=reference,
            pipeline_reference=reference,
            recurring_run_id=labels.get('pipelines.kubeflow.org/recurring-run')
            or next(
                (
                    owner.get('uid')
                    for owner in metadata.get('ownerReferences', [])
                    if owner.get('kind') == 'CronWorkflow'
                ),
                None,
            ),
            pipeline_spec={
                'apiVersion': 'argoproj.io/v1alpha1',
                'kind': 'Workflow',
                'metadata': copy.deepcopy(metadata),
                'spec': copy.deepcopy(spec),
            },
        )

    def _experiment_for_run(self, run):
        namespace = self._namespace(run.namespace)
        if run.experiment_id:
            experiment = self._find_map(
                'experiment', run.experiment_id, namespace
            )
        else:
            experiments = [
                item
                for item in self._maps('experiment', namespace)
                if item.get('data', {}).get('displayName') == 'Default'
            ]
            if experiments:
                experiment = experiments[0]
            else:
                created = self.experiment_service_create_experiment(
                    models.V2Experiment(
                        display_name='Default', namespace=namespace
                    )
                )
                experiment = self._find_map(
                    'experiment', created.experiment_id, namespace
                )
        return experiment

    def run_service_create_run(self, run, enable_caching=None, cache_key=None):
        experiment = self._experiment_for_run(run)
        namespace = experiment['metadata']['namespace']
        manifest, spec, parameters = self._workflow_spec(
            run, enable_caching, cache_key
        )
        self._prepare_staging(spec, namespace)
        annotations = {
            'pipelines.kubeflow.org/storage-state': 'AVAILABLE',
            DISPLAY_NAME: run.display_name,
            DESCRIPTION: run.description or '',
            'pipelines.kubeflow.org/parameters': json.dumps(
                parameters, allow_nan=False
            ),
        }
        annotations.update(
            {
                key: value
                for key, value in manifest.get('metadata', {})
                .get('annotations', {})
                .items()
                if key in (*ROOT_KEYS, PARAMETER_TYPES)
            }
        )
        labels = {
            **manifest.get('metadata', {}).get('labels', {}),
            EXPERIMENT: experiment['metadata']['uid'],
        }
        if run.pipeline_version_reference:
            labels[VERSION_ID] = manifest['metadata']['uid']
            annotations[TEMPLATE] = manifest['metadata']['name']
        root = (
            run.runtime_config.pipeline_root if run.runtime_config else None
        ) or manifest.get('metadata', {}).get('annotations', {}).get(
            'pipelines.kubeflow.org/artifact-repository'
        )
        if root:
            annotations['pipelines.kubeflow.org/pipeline-root'] = root
        prefix = (
            re.sub('[^a-z0-9-]', '-', run.display_name.lower()).strip('-')[:48]
            or 'run'
        )
        workflow = {
            'apiVersion': 'argoproj.io/v1alpha1',
            'kind': 'Workflow',
            'metadata': {
                'generateName': prefix + '-',
                'namespace': namespace,
                'labels': labels,
                'annotations': annotations,
            },
            'spec': spec,
        }
        return self._run(
            self.transport.request(
                'POST',
                f'/argo/api/v1/workflows/{segment(namespace)}',
                body={'namespace': namespace, 'workflow': workflow},
            )
        )

    def _workflow(self, run_id):
        known = self._known_workflows.get(run_id)
        namespace = (
            known[0]
            if known
            else self._known_namespaces.get(run_id) or self._namespace()
        )
        name = known[1] if known else None
        if name is None:
            resources = self.transport.collection(
                f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(namespace)}/workflows',
                params={'labelSelector': PIPELINE},
                kubernetes=True,
                metadata_only=True,
            )
            name = next(
                (
                    item['metadata']['name']
                    for item in resources
                    if item['metadata'].get('uid') == run_id
                ),
                None,
            )
        resource, live = None, False
        if name is not None:
            try:
                candidate = self.transport.request(
                    'GET',
                    f'/argo/api/v1/workflows/{segment(namespace)}/{segment(name)}',
                )
                if candidate.get('metadata', {}).get('uid') == run_id:
                    resource, live = candidate, True
            except models.ApiException as error:
                if error.status != 404:
                    raise
        if resource is None:
            # Names can be reused; a cached route is never permission to return
            # or mutate a different UID. The original may survive in the archive.
            resource = self.transport.request(
                'GET',
                f'/argo/api/v1/archived-workflows/{segment(run_id)}',
                params={'namespace': namespace},
            )
        if resource.get('metadata', {}).get('uid') != run_id:
            raise models.ApiException(
                status=409,
                reason='Workflow identity changed; refusing a same-name replacement.',
            )
        self._remember(resource)
        return resource, live

    def run_service_get_run(self, run_id):
        resource, live = self._workflow(run_id)
        states = self._run_states(resource['metadata']['namespace'])
        return self._run(
            resource,
            states.get(run_id, 'AVAILABLE'),
            self._pod_uids(resource) if live else None,
        )

    def _pod_uids(self, resource):
        """Pod UIDs by name while the pods still exist; absent after pod GC."""
        metadata = resource['metadata']
        try:
            pods = self.transport.collection(
                f'/kubernetes/api/v1/namespaces/{segment(metadata["namespace"])}/pods',
                params={
                    'labelSelector': 'workflows.argoproj.io/workflow='
                    + metadata['name']
                },
                kubernetes=True,
            )
        except (models.ApiException, OSError, ValueError):
            return {}
        return {
            pod['metadata']['name']: pod['metadata'].get('uid')
            for pod in pods
            if pod.get('metadata', {}).get('name')
        }

    def _pipeline_namespace(self, namespace=None):
        if namespace is not None:
            return namespace
        info = self.transport.request('GET', '/argo/api/v1/info')
        return info.get('managedNamespace') or self._namespace()

    def _versions(self, namespace):
        return self.transport.collection(
            f'/argo/api/v1/workflow-templates/{segment(namespace)}',
            params={'listOptions.labelSelector': PIPELINE},
        )

    def _pipeline(self, resource):
        self._remember(resource)
        metadata, data = resource['metadata'], resource.get('data', {})
        return models.V2Pipeline(
            pipeline_id=metadata['uid'],
            name=metadata['name'],
            display_name=data.get('displayName', metadata['name']),
            description=data.get('description'),
            created_at=timestamp(metadata.get('creationTimestamp')),
            namespace=None
            if data.get('shared') == 'true'
            else metadata['namespace'],
        )

    def _pipeline_record(self, pipeline_id):
        namespace = (
            self._known_namespaces.get(pipeline_id)
            or self._pipeline_namespace()
        )
        try:
            return self._find_map('pipeline', pipeline_id, namespace)
        except models.ApiException as error:
            if error.status != 404 or namespace == self._namespace():
                raise
            return self._find_map('pipeline', pipeline_id, self._namespace())

    def _version(self, resource):
        self._remember(resource)
        metadata = resource['metadata']
        annotations = metadata.get('annotations', {})
        manifest = copy.deepcopy(resource)
        manifest.update(
            apiVersion='argoproj.io/v1alpha1', kind='WorkflowTemplate'
        )
        return models.V2PipelineVersion(
            pipeline_id=metadata.get('labels', {}).get(PIPELINE),
            pipeline_version_id=metadata['uid'],
            name=metadata['name'],
            display_name=annotations.get(
                'pipelines.kubeflow.org/version-display-name', metadata['name']
            ),
            description=annotations.get(
                'pipelines.kubeflow.org/version-description',
                annotations.get(DESCRIPTION),
            ),
            created_at=timestamp(metadata.get('creationTimestamp')),
            code_source_url=annotations.get(
                'pipelines.kubeflow.org/code-source'
            ),
            pipeline_spec=manifest,
        )

    def pipeline_service_list_pipelines(
        self,
        namespace=None,
        page_token='',
        page_size=10,
        sort_by='',
        filter=None,
    ):
        storage_namespace = self._pipeline_namespace(namespace)
        resources = self._maps('pipeline', storage_namespace)
        values = [
            self._pipeline(resource)
            for resource in resources
            if (resource.get('data', {}).get('shared') == 'true')
            == (namespace is None)
        ]
        return self._page(
            models.V2ListPipelinesResponse,
            'pipelines',
            values,
            ['pipelines', namespace, storage_namespace],
            page_token=page_token,
            page_size=page_size,
            sort_by=sort_by,
            filter=filter,
        )

    def pipeline_service_get_pipeline(self, pipeline_id):
        return self._pipeline(self._pipeline_record(pipeline_id))

    def _create_version(self, document, pipeline, name, description=None):
        namespace = pipeline['metadata']['namespace']
        pipeline_id = pipeline['metadata']['uid']
        versions = [
            resource
            for resource in self._versions(namespace)
            if resource['metadata'].get('labels', {}).get(PIPELINE)
            == pipeline_id
        ]
        if any(
            self._version(resource).display_name == name
            for resource in versions
        ):
            raise models.ApiException(
                status=409, reason=f'Pipeline version {name!r} already exists.'
            )
        manifest = document.to_dict()
        spec = (
            manifest['spec']['workflowSpec']
            if manifest['kind'] == 'CronWorkflow'
            else manifest['spec']
        )
        resource_name = 'version-' + str(uuid4())
        labels = {
            PIPELINE: pipeline_id,
            'pipelines.kubeflow.org/version': hashlib.sha256(
                json.dumps(spec, sort_keys=True).encode()
            ).hexdigest()[:12],
        }
        annotations = {
            **manifest.get('metadata', {}).get('annotations', {}),
            DISPLAY_NAME: pipeline['data']['displayName'],
            DESCRIPTION: pipeline['data'].get('description', ''),
            'pipelines.kubeflow.org/version-display-name': name,
            'pipelines.kubeflow.org/version-description': description or '',
        }
        spec.setdefault('workflowMetadata', {}).setdefault('labels', {}).update(
            labels
        )
        resource = {
            'apiVersion': 'argoproj.io/v1alpha1',
            'kind': 'WorkflowTemplate',
            'metadata': {
                'name': resource_name,
                'namespace': namespace,
                'labels': labels,
                'annotations': annotations,
            },
            'spec': spec,
        }
        response = self.transport.request(
            'POST',
            f'/argo/api/v1/workflow-templates/{segment(namespace)}',
            body={'namespace': namespace, 'template': resource},
        )
        return self._version(response)

    def upload_pipeline(
        self, pipeline_package_path, name, description=None, namespace=None
    ):
        document = extract_pipeline(pipeline_package_path)
        storage_namespace = self._pipeline_namespace(namespace)
        resources = self._maps('pipeline', storage_namespace)
        if any(
            resource.get('data', {}).get('displayName') == name
            and (resource.get('data', {}).get('shared') == 'true')
            == (namespace is None)
            for resource in resources
        ):
            raise models.ApiException(
                status=409, reason=f'Pipeline {name!r} already exists.'
            )
        resource = {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {
                'name': 'pipeline-' + str(uuid4()),
                'namespace': storage_namespace,
                'labels': {RESOURCE: 'pipeline'},
            },
            'data': {
                'displayName': name,
                'description': description or '',
                'shared': str(namespace is None).lower(),
            },
        }
        pipeline = self.transport.request(
            'POST', self._maps_path(storage_namespace), body=resource
        )
        try:
            self._create_version(document, pipeline, name, description)
        except Exception:
            self._delete_map(pipeline)
            raise
        return self._pipeline(pipeline)

    def upload_pipeline_version(
        self, pipeline_package_path, name, pipelineid, description=None
    ):
        return self._create_version(
            extract_pipeline(pipeline_package_path),
            self._pipeline_record(pipelineid),
            name,
            description,
        )

    def pipeline_service_list_pipeline_versions(
        self, pipeline_id, page_token='', page_size=10, sort_by='', filter=None
    ):
        pipeline = self._pipeline_record(pipeline_id)
        values = [
            self._version(resource)
            for resource in self._versions(pipeline['metadata']['namespace'])
            if resource['metadata'].get('labels', {}).get(PIPELINE)
            == pipeline_id
        ]
        return self._page(
            models.V2ListPipelineVersionsResponse,
            'pipeline_versions',
            values,
            ['versions', pipeline_id],
            page_token=page_token,
            page_size=page_size,
            sort_by=sort_by,
            filter=filter,
        )

    def pipeline_service_get_pipeline_version(
        self, pipeline_id, pipeline_version_id=None
    ):
        versions = self.pipeline_service_list_pipeline_versions(
            pipeline_id, page_size=1000000, sort_by='created_at desc'
        ).pipeline_versions
        if pipeline_version_id is None and versions:
            return versions[0]
        for version in versions:
            if version.pipeline_version_id == pipeline_version_id:
                return version
        raise not_found('pipeline version', pipeline_version_id)

    def _delete_version(self, version):
        metadata = version.pipeline_spec['metadata']
        self.transport.request(
            'DELETE',
            f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(metadata["namespace"])}/workflowtemplates/{segment(metadata["name"])}',
            body={
                'apiVersion': 'v1',
                'kind': 'DeleteOptions',
                'propagationPolicy': 'Orphan',
                'preconditions': {'uid': metadata['uid']},
            },
        )
        return {}

    def pipeline_service_delete_pipeline_version(
        self, pipeline_id, pipeline_version_id
    ):
        return self._delete_version(
            self.pipeline_service_get_pipeline_version(
                pipeline_id, pipeline_version_id
            )
        )

    def pipeline_service_delete_pipeline(self, pipeline_id):
        pipeline = self._pipeline_record(pipeline_id)
        for version in self.pipeline_service_list_pipeline_versions(
            pipeline_id, page_size=1000000
        ).pipeline_versions:
            self._delete_version(version)
        return self._delete_map(pipeline)

    def _run_states(self, namespace):
        return {
            resource.get('data', {}).get('runId'): resource.get('data', {}).get(
                'storageState', 'AVAILABLE'
            )
            for resource in self._maps('run-state', namespace)
        }

    def _workflow_resources(self, namespace, tolerate_archive=False):
        """Live and archived workflows by UID.

        Listing may tolerate an unreachable archive; mutations that must
        reach every run, such as experiment archival, must not.
        """
        live = self.transport.collection(
            f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(namespace)}/workflows',
            params={'labelSelector': PIPELINE},
            kubernetes=True,
        )
        try:
            archived = self.transport.collection(
                '/argo/api/v1/archived-workflows',
                params={
                    'namespace': namespace,
                    'listOptions.labelSelector': PIPELINE,
                },
            )
        except models.ApiException as error:
            # A client authenticating directly against Kubernetes has no Argo
            # endpoint for the archive (C18); the cluster's live workflows are
            # still a faithful inventory of what it holds.
            if not tolerate_archive:
                raise
            if not self._archive_warned:
                warnings.warn(
                    'Archived runs are not listed: the Argo archive is '
                    f'unavailable ({error.status} {error.reason}). Use a native '
                    'endpoint with Argo access for full run history.',
                    stacklevel=3,
                )
                self._archive_warned = True
            archived = []
        return {
            resource['metadata']['uid']: resource
            for resource in archived + live
        }

    def _run_storage(self, run_id, state):
        workflow, _ = self._workflow(run_id)
        experiment_id = workflow['metadata'].get('labels', {}).get(EXPERIMENT)
        if state == 'AVAILABLE' and experiment_id:
            experiment = self._find_map(
                'experiment', experiment_id, workflow['metadata']['namespace']
            )
            if experiment.get('data', {}).get('storageState') == 'ARCHIVED':
                raise models.ApiException(
                    status=400,
                    reason='Unarchive the experiment first to allow the run to be restored.',
                )
        return self._set_run_storage(workflow, state)

    def _set_run_storage(self, workflow, state):
        run_id = workflow['metadata']['uid']
        namespace = workflow['metadata']['namespace']
        name = 'run-' + run_id
        path = self._maps_path(namespace) + '/' + segment(name)
        try:
            resource = self.transport.request('GET', path)
        except models.ApiException as error:
            if error.status != 404:
                raise
            resource = None
        if resource is not None:
            if resource.get('data', {}).get('runId') != run_id:
                raise models.ApiException(
                    status=409, reason='Run-state identity does not match.'
                )
            if resource['data'].get('storageState') == state:
                return {}
            resource['data']['storageState'] = state
            self.transport.request('PUT', path, body=resource)
        else:
            resource = {
                'apiVersion': 'v1',
                'kind': 'ConfigMap',
                'metadata': {
                    'name': name,
                    'namespace': namespace,
                    'labels': {RESOURCE: 'run-state'},
                },
                'data': {'runId': run_id, 'storageState': state},
            }
            self.transport.request(
                'POST', self._maps_path(namespace), body=resource
            )
        return {}

    def run_service_archive_run(self, run_id):
        return self._run_storage(run_id, 'ARCHIVED')

    def run_service_unarchive_run(self, run_id):
        return self._run_storage(run_id, 'AVAILABLE')

    def run_service_list_runs(
        self,
        page_token='',
        page_size=10,
        sort_by='',
        experiment_id=None,
        namespace=None,
        filter=None,
    ):
        namespace = self._namespace(namespace)
        if experiment_id:
            experiment = self._find_map('experiment', experiment_id, namespace)
            namespace = experiment['metadata']['namespace']
        merged = self._workflow_resources(namespace, tolerate_archive=True)
        states = self._run_states(namespace)
        values = [
            self._run(resource, states.get(uid, 'AVAILABLE'))
            for uid, resource in merged.items()
            if not experiment_id
            or resource['metadata'].get('labels', {}).get(EXPERIMENT)
            in (experiment_id, experiment['metadata']['name'])
        ]
        return self._page(
            models.V2ListRunsResponse,
            'runs',
            values,
            ['runs', namespace, experiment_id],
            page_token=page_token,
            page_size=page_size,
            sort_by=sort_by,
            filter=filter,
        )

    def run_service_terminate_run(self, run_id):
        resource, live = self._workflow(run_id)
        if not live:
            raise models.ApiException(
                status=400,
                reason='A completed archived run cannot be terminated.',
            )
        metadata = resource['metadata']
        if self.transport.kubernetes_host:
            resource.setdefault('spec', {})['shutdown'] = 'Terminate'
            self.transport.request(
                'PUT',
                f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(metadata["namespace"])}/workflows/{segment(metadata["name"])}',
                body=resource,
            )
            return {}
        self.transport.request(
            'PUT',
            f'/argo/api/v1/workflows/{segment(metadata["namespace"])}/{segment(metadata["name"])}/terminate',
            body={'namespace': metadata['namespace'], 'name': metadata['name']},
        )
        return {}

    def run_service_delete_run(self, run_id):
        resource, live = self._workflow(run_id)
        metadata = resource['metadata']
        if live:
            self.transport.request(
                'DELETE',
                f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(metadata["namespace"])}/workflows/{segment(metadata["name"])}',
                body={
                    'apiVersion': 'v1',
                    'kind': 'DeleteOptions',
                    'preconditions': {'uid': run_id},
                },
            )
        try:
            self.transport.request(
                'DELETE',
                f'/argo/api/v1/archived-workflows/{segment(run_id)}',
                params={'namespace': metadata['namespace']},
            )
        except models.ApiException as error:
            if error.status != 404:
                raise
        for state in self._maps('run-state', metadata['namespace']):
            if state.get('data', {}).get('runId') == run_id:
                self._delete_map(state)
        return {}

    def _schedules(self, namespace):
        return self.transport.collection(
            f'/argo/api/v1/cron-workflows/{segment(namespace)}',
            params={'listOptions.labelSelector': PIPELINE},
        )

    def _schedule(self, recurring_run_id):
        namespace = (
            self._known_namespaces.get(recurring_run_id) or self._namespace()
        )
        resource = next(
            (
                item
                for item in self._schedules(namespace)
                if item['metadata'].get('uid') == recurring_run_id
            ),
            None,
        )
        if resource is None:
            raise not_found('recurring run', recurring_run_id)
        current = self.transport.request(
            'GET',
            f'/argo/api/v1/cron-workflows/{segment(namespace)}/{segment(resource["metadata"]["name"])}',
        )
        if current.get('metadata', {}).get('uid') != recurring_run_id:
            raise models.ApiException(
                status=409,
                reason='Recurring-run identity changed; refusing a same-name replacement.',
            )
        return self._remember(current)

    def _recurring(self, resource):
        self._remember(resource)
        metadata, spec = resource['metadata'], resource['spec']
        annotations = metadata.get('annotations', {})
        configuration = json.loads(annotations.get(SCHEDULE_CONFIG, '{}'))
        expressions = spec.get('schedules') or []
        expression = expressions[0] if expressions else ''
        interval = re.fullmatch(r'@every ([0-9]+)s', expression)
        trigger = configuration.setdefault('trigger', {})
        if interval:
            trigger.update(kind='periodic', interval_second=int(interval[1]))
        else:
            timezone = spec.get('timezone') or 'UTC'
            if not trigger.get('cron') or cron_schedule(trigger['cron']) != (
                expression,
                timezone,
            ):
                trigger.update(
                    kind='cron',
                    cron=(f'TZ={timezone} ' if timezone != 'UTC' else '')
                    + expression,
                )
        workflow = spec.get('workflowSpec', {})
        labels = spec.get('workflowMetadata', {}).get('labels', {})
        values = json.loads(
            spec.get('workflowMetadata', {})
            .get('annotations', {})
            .get('pipelines.kubeflow.org/parameters', '{}')
        )
        reference = (
            models.V2PipelineVersionReference(
                pipeline_id=labels.get(PIPELINE),
                pipeline_version_id=labels[VERSION_ID],
            )
            if labels.get(VERSION_ID)
            else None
        )
        limit = configuration.get(
            'max_concurrency',
            1 if spec.get('concurrencyPolicy') == 'Forbid' else None,
        )
        # The API server records each manager's last write; the newest is the
        # last time anything changed this schedule.
        updated = max(
            (
                timestamp(entry['time'])
                for entry in metadata.get('managedFields', [])
                if entry.get('time')
            ),
            default=None,
        )
        return models.V2RecurringRun(
            recurring_run_id=metadata['uid'],
            display_name=annotations.get(DISPLAY_NAME, metadata['name']),
            description=annotations.get(DESCRIPTION),
            namespace=metadata['namespace'],
            experiment_id=labels.get(EXPERIMENT),
            status='DISABLED' if spec.get('suspend') else 'ENABLED',
            mode='DISABLE' if spec.get('suspend') else 'ENABLE',
            no_catchup=spec.get('startingDeadlineSeconds', 0) == 0,
            max_concurrency=str(limit) if limit is not None else None,
            trigger=trigger_from_config(configuration),
            service_account=workflow.get('serviceAccountName'),
            created_at=timestamp(metadata.get('creationTimestamp')),
            updated_at=updated or timestamp(metadata.get('creationTimestamp')),
            pipeline_version_reference=reference,
            pipeline_version_id=labels.get(VERSION_ID),
            runtime_config=models.V2RuntimeConfig(
                parameters=values,
                pipeline_root=spec.get('workflowMetadata', {})
                .get('annotations', {})
                .get('pipelines.kubeflow.org/pipeline-root'),
            ),
            pipeline_spec={
                'apiVersion': 'argoproj.io/v1alpha1',
                'kind': 'CronWorkflow',
                'metadata': copy.deepcopy(metadata),
                'spec': copy.deepcopy(spec),
            },
        )

    def recurring_run_service_create_recurring_run(
        self, recurring_run, enable_caching=None, cache_key=None
    ):
        spec, configuration = schedule_settings(recurring_run)
        manifest, workflow, parameters = self._workflow_spec(
            recurring_run, enable_caching, cache_key
        )
        experiment = self._experiment_for_run(recurring_run)
        namespace = experiment['metadata']['namespace']
        self._prepare_staging(workflow, namespace)
        name = 'schedule-' + str(uuid4())
        labels = {
            **manifest.get('metadata', {}).get('labels', {}),
            EXPERIMENT: experiment['metadata']['uid'],
        }
        if recurring_run.pipeline_version_reference:
            labels[VERSION_ID] = manifest['metadata']['uid']
        workflow_annotations = {
            'pipelines.kubeflow.org/storage-state': 'AVAILABLE',
            'pipelines.kubeflow.org/parameters': json.dumps(
                parameters, allow_nan=False
            ),
        }
        workflow_annotations.update(
            {
                key: value
                for key, value in manifest.get('metadata', {})
                .get('annotations', {})
                .items()
                if key in (*ROOT_KEYS, PARAMETER_TYPES)
            }
        )
        root = (
            recurring_run.runtime_config.pipeline_root
            if recurring_run.runtime_config
            else None
        ) or manifest.get('metadata', {}).get('annotations', {}).get(
            'pipelines.kubeflow.org/artifact-repository'
        )
        if root:
            workflow_annotations['pipelines.kubeflow.org/pipeline-root'] = root
        if manifest.get('metadata', {}).get('uid'):
            workflow_annotations[TEMPLATE] = manifest['metadata']['name']
        semaphore = None
        if configuration['max_concurrency'] > 1:
            semaphore = {
                'apiVersion': 'v1',
                'kind': 'ConfigMap',
                'metadata': {
                    'name': name + '-limit',
                    'namespace': namespace,
                    'labels': {RESOURCE: 'schedule-limit'},
                },
                'data': {'limit': str(configuration['max_concurrency'])},
            }
            semaphore = self.transport.request(
                'POST', self._maps_path(namespace), body=semaphore
            )
            workflow.setdefault('synchronization', {}).setdefault(
                'semaphores', []
            ).append(
                {
                    'configMapKeyRef': {
                        'name': semaphore['metadata']['name'],
                        'key': 'limit',
                    }
                }
            )
        spec.update(
            workflowSpec=workflow,
            workflowMetadata={
                'labels': labels,
                'annotations': workflow_annotations,
            },
        )
        resource = {
            'apiVersion': 'argoproj.io/v1alpha1',
            'kind': 'CronWorkflow',
            'metadata': {
                'name': name,
                'namespace': namespace,
                'labels': labels,
                'annotations': {
                    DISPLAY_NAME: recurring_run.display_name,
                    DESCRIPTION: recurring_run.description or '',
                    SCHEDULE_CONFIG: json.dumps(configuration),
                },
            },
            'spec': spec,
        }
        try:
            created = self.transport.request(
                'POST',
                f'/argo/api/v1/cron-workflows/{segment(namespace)}',
                body={'namespace': namespace, 'cronWorkflow': resource},
            )
        except Exception:
            if semaphore:
                self._delete_map(semaphore)
            raise
        return self._recurring(created)

    def recurring_run_service_get_recurring_run(self, recurring_run_id):
        return self._recurring(self._schedule(recurring_run_id))

    def recurring_run_service_list_recurring_runs(
        self,
        page_token='',
        page_size=10,
        sort_by='',
        experiment_id=None,
        namespace=None,
        filter=None,
    ):
        namespace = self._namespace(namespace)
        if experiment_id:
            namespace = self._find_map('experiment', experiment_id, namespace)[
                'metadata'
            ]['namespace']
        values = [
            self._recurring(resource)
            for resource in self._schedules(namespace)
            if not experiment_id
            or resource['spec']
            .get('workflowMetadata', {})
            .get('labels', {})
            .get(EXPERIMENT)
            == experiment_id
        ]
        return self._page(
            models.V2ListRecurringRunsResponse,
            'recurring_runs',
            values,
            ['recurring', namespace, experiment_id],
            page_token=page_token,
            page_size=page_size,
            sort_by=sort_by,
            filter=filter,
        )

    def _schedule_suspended(self, recurring_run_id, suspend):
        return self._set_schedule_suspended(
            self._schedule(recurring_run_id), suspend
        )

    def _set_schedule_suspended(self, resource, suspend):
        if resource['spec'].get('suspend', False) == suspend:
            return {}
        resource['spec']['suspend'] = suspend
        metadata = resource['metadata']
        self.transport.request(
            'PUT',
            f'/argo/api/v1/cron-workflows/{segment(metadata["namespace"])}/{segment(metadata["name"])}',
            body={
                'namespace': metadata['namespace'],
                'name': metadata['name'],
                'cronWorkflow': resource,
            },
        )
        return {}

    def recurring_run_service_enable_recurring_run(self, recurring_run_id):
        return self._schedule_suspended(recurring_run_id, False)

    def recurring_run_service_disable_recurring_run(self, recurring_run_id):
        return self._schedule_suspended(recurring_run_id, True)

    def recurring_run_service_delete_recurring_run(self, recurring_run_id):
        resource = self._schedule(recurring_run_id)
        metadata = resource['metadata']
        # Orphan already-created workflows. Their semaphore configuration remains
        # available so queued/running executions are not broken by deleting a schedule.
        self.transport.request(
            'DELETE',
            f'/kubernetes/apis/argoproj.io/v1alpha1/namespaces/{segment(metadata["namespace"])}/cronworkflows/{segment(metadata["name"])}',
            body={
                'apiVersion': 'v1',
                'kind': 'DeleteOptions',
                'propagationPolicy': 'Orphan',
                'preconditions': {'uid': recurring_run_id},
            },
        )
        return {}
