# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Stock's kfp.kubernetes unit tests for DRA resource claims, init containers
and security contexts, ported to the native boundary.

See ``setters_test.py`` for the approach and the shared helpers.
"""

import json

import pytest

from kfp import dsl, kubernetes
from kfp.kubernetes.setters_test import (
    comp,
    lowered,
    pipeline_input,
    recorded,
    task_output,
)


@dsl.component
def print_greeting():
    print('hello world')


@dsl.component()
def comp_with_dict_output() -> dict:
    return {'resourceClaimTemplateName': 'gpu-claim-template'}


class TestResourceClaim:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_resource_claim(
                task, resource_claim_template_name='gpu-claim-template'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {'resourceClaimTemplateName': 'gpu-claim-template'}
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert template['resourceClaims'] == [
            {
                'name': 'gpu-claim-template',
                'resourceClaimTemplateName': 'gpu-claim-template',
            }
        ]
        assert template['container']['resources']['claims'] == [
            {'name': 'gpu-claim-template'}
        ]

    def test_add_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_resource_claim(
                task, resource_claim_template_name='gpu-claim-template'
            )
            kubernetes.add_resource_claim(
                task, resource_claim_template_name='nic-claim-template'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {'resourceClaimTemplateName': 'gpu-claim-template'},
                    {'resourceClaimTemplateName': 'nic-claim-template'},
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert [c['name'] for c in template['resourceClaims']] == [
            'gpu-claim-template',
            'nic-claim-template',
        ]
        assert template['container']['resources']['claims'] == [
            {'name': 'gpu-claim-template'},
            {'name': 'nic-claim-template'},
        ]

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_toleration(
                task, key='key1', operator='Equal', value='value1'
            )
            kubernetes.add_resource_claim(
                task, resource_claim_template_name='gpu-claim-template'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'tolerations': [
                    {'key': 'key1', 'operator': 'Equal', 'value': 'value1'}
                ],
                'podResourceClaims': [
                    {'resourceClaimTemplateName': 'gpu-claim-template'}
                ],
            }
        }

    def test_coexists_with_set_accelerator_limit(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            task.set_accelerator_limit(1)
            kubernetes.add_resource_claim(
                task, resource_claim_template_name='gpu-claim-template'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {'resourceClaimTemplateName': 'gpu-claim-template'}
                ]
            }
        }

    def test_empty_name_raises_error(self):
        with pytest.raises(
            ValueError,
            match='resource_claim_template_name must be a non-empty string',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_resource_claim(
                    comp(), resource_claim_template_name=''
                )


class TestResourceClaimJSON:
    def test_pipeline_input_parameter(self):
        @dsl.pipeline
        def my_pipeline(resource_claim: dict):
            task = comp()
            kubernetes.add_resource_claim_json(
                task, resource_claim_json=resource_claim
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {'resourceClaimJson': pipeline_input('resource_claim')}
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert 'resourceClaims' not in template
        assert 'resourceClaims' in template['podSpecPatch']

    def test_static_resource_claim_config(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_resource_claim_json(
                task,
                resource_claim_json=kubernetes.ResourceClaimConfig(
                    resource_claim_template_name='gpu-claim-template'
                ),
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {
                        'resourceClaimJson': {
                            'runtimeValue': {
                                'constant': {
                                    'resourceClaimTemplateName': 'gpu-claim-template'
                                }
                            }
                        }
                    }
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert template['resourceClaims'] == [
            {
                'name': 'gpu-claim-template',
                'resourceClaimTemplateName': 'gpu-claim-template',
            }
        ]
        assert template['container']['resources']['claims'] == [
            {'name': 'gpu-claim-template'}
        ]

    def test_static_resource_claim_config_list(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_resource_claim_json(
                task,
                resource_claim_json=[
                    kubernetes.ResourceClaimConfig(
                        resource_claim_template_name='gpu-claim-template'
                    ),
                    kubernetes.ResourceClaimConfig(
                        resource_claim_template_name='nic-claim-template'
                    ),
                ],
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {
                        'resourceClaimJson': {
                            'runtimeValue': {
                                'constant': {
                                    'resourceClaimTemplateName': 'gpu-claim-template'
                                }
                            }
                        }
                    },
                    {
                        'resourceClaimJson': {
                            'runtimeValue': {
                                'constant': {
                                    'resourceClaimTemplateName': 'nic-claim-template'
                                }
                            }
                        }
                    },
                ]
            }
        }
        assert [
            c['name'] for c in lowered(my_pipeline)['comp']['resourceClaims']
        ] == ['gpu-claim-template', 'nic-claim-template']

    def test_list_with_invalid_element_raises_error(self):
        with pytest.raises(ValueError, match='ResourceClaimConfig'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_resource_claim_json(
                    comp(),
                    resource_claim_json=[
                        kubernetes.ResourceClaimConfig(
                            resource_claim_template_name='gpu-claim-template'
                        ),
                        {'resourceClaimTemplateName': 'bad'},
                    ],
                )

    def test_invalid_type_raises_error(self):
        with pytest.raises(
            ValueError,
            match='resource_claim_json must be a PipelineParameterChannel',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_resource_claim_json(
                    comp(), resource_claim_json=42
                )

    def test_upstream_task_output(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_dict_output()
            kubernetes.add_resource_claim_json(
                t1, resource_claim_json=t2.output
            )

        tasks = my_pipeline.pipeline_spec.pipeline.tasks
        assert (
            tasks['comp-with-dict-output'].outputs['Output'].channel_type
            == 'Dict'
        ), 'Stock required a STRUCT output for the claim document'
        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podResourceClaims': [
                    {'resourceClaimJson': task_output('comp-with-dict-output')}
                ]
            }
        }


class TestResourceClaimConfig:
    def test_valid_creation(self):
        config = kubernetes.ResourceClaimConfig(
            resource_claim_template_name='gpu-claim-template'
        )
        assert config.resource_claim_template_name == 'gpu-claim-template'

    def test_empty_name_raises_error(self):
        with pytest.raises(ValueError):
            kubernetes.ResourceClaimConfig(resource_claim_template_name='')

    def test_missing_name_raises_error(self):
        with pytest.raises(TypeError):
            kubernetes.ResourceClaimConfig()

    def test_to_dict(self):
        config = kubernetes.ResourceClaimConfig(
            resource_claim_template_name='gpu-claim-template'
        )
        assert config.to_dict() == {
            'resourceClaimTemplateName': 'gpu-claim-template'
        }

    @pytest.mark.parametrize(
        'config, expected',
        [
            pytest.param(
                kubernetes.ResourceClaimConfig('gpu-claim-template'),
                {'resourceClaimTemplateName': 'gpu-claim-template'},
                id='single-claim',
            ),
            pytest.param(
                [
                    kubernetes.ResourceClaimConfig('gpu-claim-template'),
                    kubernetes.ResourceClaimConfig('nic-claim-template'),
                ],
                [
                    {'resourceClaimTemplateName': 'gpu-claim-template'},
                    {'resourceClaimTemplateName': 'nic-claim-template'},
                ],
                id='claim-list',
            ),
        ],
    )
    def test_serializes_as_runtime_parameter(self, config, expected):
        """Stock serialized the config through the REST ApiClient; natively it
        travels as a plain JSON run parameter."""
        from kfp.server_api import V2RuntimeConfig

        runtime_config = V2RuntimeConfig(parameters={'resource_claim': config})
        assert runtime_config.to_dict()['parameters']['resource_claim'] == (
            expected
        )
        assert json.loads(json.dumps(config)) == expected


class TestAddInitContainer:
    def test_add_init_container_all_fields(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.empty_dir_mount(
                task, volume_name='config-volume', mount_path='/config'
            )
            kubernetes.add_init_container(
                task,
                name='fetch-config',
                image='busybox:1.36',
                command=['sh', '-c'],
                args=['wget -O /config/settings.json $CONFIG_URL'],
                env={'CONFIG_URL': 'http://config-server/settings.json'},
                volume_mounts={'config-volume': '/config'},
            )

        init_container = {
            'name': 'fetch-config',
            'image': 'busybox:1.36',
            'command': ['sh', '-c'],
            'args': ['wget -O /config/settings.json $CONFIG_URL'],
            'env': [
                {
                    'name': 'CONFIG_URL',
                    'value': 'http://config-server/settings.json',
                }
            ],
            'volumeMounts': [
                {'volumeName': 'config-volume', 'mountPath': '/config'}
            ],
        }
        assert recorded(my_pipeline)['exec-print-greeting'][
            'initContainers'
        ] == [init_container]
        lowered_init = lowered(my_pipeline)['print-greeting']['initContainers'][
            0
        ]
        assert {
            key: lowered_init[key]
            for key in ('name', 'image', 'command', 'args', 'env')
        } == {
            key: init_container[key]
            for key in ('name', 'image', 'command', 'args', 'env')
        }
        assert lowered_init['volumeMounts'] == [
            {'name': 'config-volume', 'mountPath': '/config'}
        ]

    def test_add_init_container_minimal(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.add_init_container(
                task, name='wait-for-database', image='busybox:1.36'
            )

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'initContainers': [
                    {'name': 'wait-for-database', 'image': 'busybox:1.36'}
                ]
            }
        }

    def test_add_init_container_multiple_preserves_order(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.add_init_container(
                task, name='first-init', image='busybox:1.36'
            )
            kubernetes.add_init_container(
                task, name='second-init', image='busybox:1.36'
            )

        init_containers = recorded(my_pipeline)['exec-print-greeting'][
            'initContainers'
        ]
        assert [c['name'] for c in init_containers] == [
            'first-init',
            'second-init',
        ]
        assert [
            c['name']
            for c in lowered(my_pipeline)['print-greeting']['initContainers']
        ] == ['first-init', 'second-init']

    def test_add_init_container_reserved_name(self):
        with pytest.raises(
            ValueError,
            match=r'Init container name "kfp-launcher" is reserved by Kubeflow Pipelines.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(), name='kfp-launcher', image='busybox:1.36'
                )

    def test_add_init_container_empty_name(self):
        with pytest.raises(
            ValueError, match=r'Argument for "name" must be a non-empty string.'
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(), name='', image='busybox:1.36'
                )

    def test_add_init_container_empty_image(self):
        with pytest.raises(
            ValueError,
            match=r'Argument for "image" must be a non-empty string.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(), name='fetch-config', image=''
                )

    def test_add_init_container_duplicate_name(self):
        with pytest.raises(
            ValueError,
            match=r'An init container named "fetch-config" was already added to this task.',
        ):

            @dsl.pipeline
            def my_pipeline():
                task = print_greeting()
                kubernetes.add_init_container(
                    task, name='fetch-config', image='busybox:1.36'
                )
                kubernetes.add_init_container(
                    task, name='fetch-config', image='busybox:1.36'
                )

    def test_add_init_container_native_sidecar(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.add_init_container(
                task,
                name='log-forwarder',
                image='busybox:1.36',
                restart_policy='Always',
            )

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'initContainers': [
                    {
                        'name': 'log-forwarder',
                        'image': 'busybox:1.36',
                        'restartPolicy': 'Always',
                    }
                ]
            }
        }
        assert (
            lowered(my_pipeline)['print-greeting']['initContainers'][0][
                'restartPolicy'
            ]
            == 'Always'
        )

    def test_add_init_container_invalid_restart_policy(self):
        with pytest.raises(
            ValueError,
            match=r'Argument for "restart_policy" must be "Always" if provided. Got: Never.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(),
                    name='log-forwarder',
                    image='busybox:1.36',
                    restart_policy='Never',
                )

    def test_add_init_container_sidecar_with_resources(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.add_init_container(
                task,
                name='log-forwarder',
                image='busybox:1.36',
                restart_policy='Always',
                resource_requests={'cpu': '250m', 'memory': '128Mi'},
                resource_limits={'cpu': '500m', 'memory': '256Mi'},
            )

        resources = {
            'requests': {'cpu': '250m', 'memory': '128Mi'},
            'limits': {'cpu': '500m', 'memory': '256Mi'},
        }
        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'initContainers': [
                    {
                        'name': 'log-forwarder',
                        'image': 'busybox:1.36',
                        'restartPolicy': 'Always',
                        'resources': resources,
                    }
                ]
            }
        }
        assert (
            lowered(my_pipeline)['print-greeting']['initContainers'][0][
                'resources'
            ]
            == resources
        )

    def test_add_init_container_empty_resource_quantity(self):
        with pytest.raises(
            ValueError,
            match=r'Resource names and quantities in "resource_limits" must be non-empty strings.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(),
                    name='log-forwarder',
                    image='busybox:1.36',
                    resource_limits={'cpu': ''},
                )

    def test_add_init_container_empty_env_name(self):
        with pytest.raises(
            ValueError,
            match=r'Environment variable names in "env" must be non-empty strings.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(),
                    name='fetch-config',
                    image='busybox:1.36',
                    env={'': 'value'},
                )

    def test_add_init_container_relative_mount_path(self):
        with pytest.raises(
            ValueError,
            match=r'Mount path for volume "config-volume" must be an absolute path. Got: config.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(),
                    name='fetch-config',
                    image='busybox:1.36',
                    volume_mounts={'config-volume': 'config'},
                )

    @pytest.mark.parametrize('argument', ['command', 'args'])
    @pytest.mark.parametrize('bad', ['echo hi', ''])
    def test_plain_string_command_or_args_raises(self, argument, bad):
        with pytest.raises(TypeError, match='must be a list of strings'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_init_container(
                    print_greeting(),
                    name='init',
                    image='busybox',
                    **{argument: bad},
                )

    def test_command_and_args_lists_still_work(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_init_container(
                print_greeting(),
                name='init',
                image='busybox',
                command=['echo', 'hi'],
                args=['foo'],
            )

        init = recorded(my_pipeline)['exec-print-greeting']['initContainers'][0]
        assert init['command'] == ['echo', 'hi']
        assert init['args'] == ['foo']


class TestSecurityContext:
    def test_security_context_all_fields(self):
        @dsl.pipeline
        def my_pipeline():
            task = print_greeting()
            kubernetes.set_security_context(
                task, run_as_user=65534, run_as_group=0
            )

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'securityContext': {'runAsUser': '65534', 'runAsGroup': '0'}
            }
        }
        context = lowered(my_pipeline)['print-greeting']['container'][
            'securityContext'
        ]
        assert context['runAsUser'] == 65534
        assert context['runAsGroup'] == 0
        assert context['allowPrivilegeEscalation'] is False, (
            'The identity fields add to the baseline hardening'
        )

    def test_security_context_negative_run_as_user(self):
        with pytest.raises(
            ValueError,
            match=r'Argument for "run_as_user" must be greater than or equal to 0. Got invalid input: -1.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(
                    print_greeting(), run_as_user=-1
                )

    def test_security_context_negative_run_as_group(self):
        with pytest.raises(
            ValueError,
            match=r'Argument for "run_as_group" must be greater than or equal to 0. Got invalid input: -2.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(
                    print_greeting(), run_as_group=-2
                )

    def test_security_context_no_arguments(self):
        with pytest.raises(
            ValueError,
            match=r'At least one security context field must be provided.',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(print_greeting())

    def test_security_context_run_as_user_only(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.set_security_context(print_greeting(), run_as_user=65534)

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {'securityContext': {'runAsUser': '65534'}}
        }

    def test_security_context_run_as_group_only(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.set_security_context(print_greeting(), run_as_group=0)

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {'securityContext': {'runAsGroup': '0'}}
        }
        context = lowered(my_pipeline)['print-greeting']['container'][
            'securityContext'
        ]
        assert context['runAsGroup'] == 0
        assert 'runAsUser' not in context

    def test_security_context_bool_run_as_user(self):
        with pytest.raises(
            TypeError,
            match=r'Argument for "run_as_user" must be an int, not bool',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(
                    print_greeting(), run_as_user=True
                )

    def test_security_context_bool_run_as_group(self):
        with pytest.raises(
            TypeError,
            match=r'Argument for "run_as_group" must be an int, not bool',
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(
                    print_greeting(), run_as_group=True
                )

    @pytest.mark.parametrize('run_as_non_root', [True, False])
    def test_security_context_run_as_non_root(self, run_as_non_root):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.set_security_context(
                print_greeting(), run_as_non_root=run_as_non_root
            )

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'securityContext': {'runAsNonRoot': run_as_non_root}
            }
        }
        assert (
            lowered(my_pipeline)['print-greeting']['container'][
                'securityContext'
            ]['runAsNonRoot']
            is run_as_non_root
        )

    def test_security_context_all_fields_with_non_root(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.set_security_context(
                print_greeting(),
                run_as_user=65534,
                run_as_group=0,
                run_as_non_root=True,
            )

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {
                'securityContext': {
                    'runAsUser': '65534',
                    'runAsGroup': '0',
                    'runAsNonRoot': True,
                }
            }
        }

    def test_security_context_run_as_non_root_wrong_type(self):
        with pytest.raises(
            TypeError, match=r'Argument for "run_as_non_root" must be a bool'
        ):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_security_context(
                    print_greeting(), run_as_non_root=1
                )

    def test_security_context_run_as_user_zero(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.set_security_context(print_greeting(), run_as_user=0)

        assert recorded(my_pipeline) == {
            'exec-print-greeting': {'securityContext': {'runAsUser': '0'}}
        }
        assert (
            lowered(my_pipeline)['print-greeting']['container'][
                'securityContext'
            ]['runAsUser']
            == 0
        )
