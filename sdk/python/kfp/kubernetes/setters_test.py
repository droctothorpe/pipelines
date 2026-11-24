# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Stock's kfp.kubernetes unit tests for secrets and config maps, ported to the
native boundary; the sibling setters tests import this module's helpers.

Stock asserted the per-executor ``platform_spec`` IR. The setters are
unchanged, so the same expectations hold for each task's recorded
``platform_config['kubernetes']``; representative cases also check the pod
template the Argo compiler lowers them into. Volume names are a compiler
detail, so lowered checks key volumes by mount path and assert the object
they reference. Volumes, env and pod settings continue in
``setters_volumes_test.py``, scheduling in ``setters_scheduling_test.py`` and
resource claims, init containers and security contexts in
``setters_pod_test.py``.
"""

import os
import tempfile

import yaml

from kfp import compiler, dsl, kubernetes


@dsl.component
def comp():
    pass


@dsl.component()
def comp_with_output() -> str:
    pass


def recorded(pipeline):
    """Each task's recorded Kubernetes configuration, keyed like stock's
    executors."""
    return {
        'exec-' + name: task.platform_config['kubernetes']
        for name, task in pipeline.pipeline_spec.pipeline.tasks.items()
        if 'kubernetes' in task.platform_config
    }


def lowered(pipeline):
    """Container templates of the compiled Argo document, keyed by task
    name."""
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'pipeline.yaml')
        compiler.Compiler().compile(pipeline, path)
        with open(path) as stream:
            templates = yaml.safe_load(stream)['spec']['templates']
    return {
        template['name'].split('-', 1)[1]: template
        for template in templates
        if 'container' in template
    }


def mounted(template):
    """The volume source behind each mount path, without the compiler-chosen
    volume name."""
    sources = {v['name']: v for v in template.get('volumes', [])}
    return {
        mount['mountPath']: {
            key: value
            for key, value in sources[mount['name']].items()
            if key != 'name'
        }
        for mount in template['container'].get('volumeMounts', [])
    }


def mount_options(template, mount_path):
    """Mount settings other than the volume name and path."""
    mount = next(
        m
        for m in template['container']['volumeMounts']
        if m['mountPath'] == mount_path
    )
    return {k: v for k, v in mount.items() if k not in ('name', 'mountPath')}


def env_refs(template):
    return {
        entry['name']: entry['valueFrom']
        for entry in template['container'].get('env', [])
        if 'valueFrom' in entry
    }


def constant(value):
    return {'runtimeValue': {'constant': value}}


def pipeline_input(name):
    return {'componentInputParameter': name}


def task_output(producer):
    return {
        'taskOutputParameter': {
            'outputParameterKey': 'Output',
            'producerTask': producer,
        }
    }


def reference(field, name):
    """The name binding a setter records; literals also keep the deprecated
    plain field."""
    if isinstance(name, str):
        return {field: name, field + 'Parameter': constant(name)}
    return {field + 'Parameter': name}


def secret_as_volume(name, mount_path, optional=False):
    return {
        **reference('secretName', name),
        'mountPath': mount_path,
        'optional': optional,
    }


def secret_as_env(name, key_to_env, optional=False):
    return {
        **reference('secretName', name),
        'keyToEnv': [
            {'secretKey': key, 'envVar': env} for key, env in key_to_env.items()
        ],
        'optional': optional,
    }


def config_map_as_volume(name, mount_path, optional=False):
    return {
        **reference('configMapName', name),
        'mountPath': mount_path,
        'optional': optional,
    }


def config_map_as_env(name, key_to_env, optional=False):
    return {
        **reference('configMapName', name),
        'keyToEnv': [
            {'configMapKey': key, 'envVar': env}
            for key, env in key_to_env.items()
        ],
        'optional': optional,
    }


def pvc_mount(name, mount_path, sub_path=None):
    binding = (
        {'constant': name, 'pvcNameParameter': constant(name)}
        if isinstance(name, str)
        else {**name, 'pvcNameParameter': name}
    )
    return {
        **binding,
        'mountPath': mount_path,
        **({'subPath': sub_path} if sub_path else {}),
    }


def image_pull_secret(name):
    return reference('secretName', name)


class TestUseSecretAsVolume:
    def test_use_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name', mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume('secret-name', 'secretpath')
                ]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert mounted(template)['secretpath'] == {
            'secret': {'secretName': 'secret-name', 'optional': False}
        }
        assert mount_options(template, 'secretpath') == {'readOnly': True}

    def test_use_one_optional_true(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task,
                secret_name='secret-name',
                mount_path='secretpath',
                optional=True,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume('secret-name', 'secretpath', optional=True)
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp'])['secretpath'] == {
            'secret': {'secretName': 'secret-name', 'optional': True}
        }

    def test_use_one_optional_false(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task,
                secret_name='secret-name',
                mount_path='secretpath',
                optional=False,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume('secret-name', 'secretpath')
                ]
            }
        }

    def test_use_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name1', mount_path='secretpath1'
            )
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name2', mount_path='secretpath2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume('secret-name1', 'secretpath1'),
                    secret_as_volume('secret-name2', 'secretpath2'),
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp']) == {
            'secretpath1': {
                'secret': {'secretName': 'secret-name1', 'optional': False}
            },
            'secretpath2': {
                'secret': {'secretName': 'secret-name2', 'optional': False}
            },
        }

    def test_preserves_secret_as_env(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name1',
                secret_key_to_env={'password': 'SECRET_VAR'},
            )
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name2', mount_path='secretpath2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env('secret-name1', {'password': 'SECRET_VAR'})
                ],
                'secretAsVolume': [
                    secret_as_volume('secret-name2', 'secretpath2')
                ],
            }
        }

    def test_alongside_pvc_mount(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name', mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'secretAsVolume': [
                    secret_as_volume('secret-name', 'secretpath')
                ],
            }
        }
        assert mounted(lowered(my_pipeline)['comp']) == {
            'path': {'persistentVolumeClaim': {'claimName': 'pvc-name'}},
            'secretpath': {
                'secret': {'secretName': 'secret-name', 'optional': False}
            },
        }

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(secret_name_input_1: str):
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name=secret_name_input_1, mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume(
                        pipeline_input('secret_name_input_1'), 'secretpath'
                    )
                ]
            }
        }
        source = mounted(lowered(my_pipeline)['comp'])['secretpath']['secret']
        assert source['secretName'].startswith('{{inputs.parameters.')

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(secret_name_input_1: str, secret_name_input_2: str):
            t1 = comp()
            kubernetes.use_secret_as_volume(
                t1, secret_name=secret_name_input_1, mount_path='secretpath'
            )
            kubernetes.use_secret_as_volume(
                t1, secret_name=secret_name_input_2, mount_path='secretpath'
            )
            t2 = comp()
            kubernetes.use_secret_as_volume(
                t2, secret_name=secret_name_input_2, mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume(
                        pipeline_input('secret_name_input_1'), 'secretpath'
                    ),
                    secret_as_volume(
                        pipeline_input('secret_name_input_2'), 'secretpath'
                    ),
                ]
            },
            'exec-comp-2': {
                'secretAsVolume': [
                    secret_as_volume(
                        pipeline_input('secret_name_input_2'), 'secretpath'
                    )
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.use_secret_as_volume(
                t1, secret_name=t2.output, mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume(
                        task_output('comp-with-output'), 'secretpath'
                    )
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            kubernetes.use_secret_as_volume(
                t1, secret_name=t2.output, mount_path='secretpath'
            )
            kubernetes.use_secret_as_volume(
                t1, secret_name=t3.output, mount_path='secretpath'
            )
            t4 = comp()
            kubernetes.use_secret_as_volume(
                t4, secret_name=t2.output, mount_path='secretpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume(
                        task_output('comp-with-output'), 'secretpath'
                    ),
                    secret_as_volume(
                        task_output('comp-with-output-2'), 'secretpath'
                    ),
                ]
            },
            'exec-comp-2': {
                'secretAsVolume': [
                    secret_as_volume(
                        task_output('comp-with-output'), 'secretpath'
                    )
                ]
            },
        }


class TestUseSecretAsEnv:
    def test_use_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name',
                secret_key_to_env={
                    'username': 'USERNAME',
                    'password': 'PASSWORD',
                },
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        'secret-name',
                        {'username': 'USERNAME', 'password': 'PASSWORD'},
                    )
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp']) == {
            'USERNAME': {
                'secretKeyRef': {
                    'name': 'secret-name',
                    'key': 'username',
                    'optional': False,
                }
            },
            'PASSWORD': {
                'secretKeyRef': {
                    'name': 'secret-name',
                    'key': 'password',
                    'optional': False,
                }
            },
        }

    def test_use_one_optional_true(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name',
                secret_key_to_env={
                    'username': 'USERNAME',
                    'password': 'PASSWORD',
                },
                optional=True,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        'secret-name',
                        {'username': 'USERNAME', 'password': 'PASSWORD'},
                        optional=True,
                    )
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp'])['USERNAME'][
            'secretKeyRef'
        ]['optional']

    def test_use_one_optional_false(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name',
                secret_key_to_env={
                    'username': 'USERNAME',
                    'password': 'PASSWORD',
                },
                optional=False,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        'secret-name',
                        {'username': 'USERNAME', 'password': 'PASSWORD'},
                    )
                ]
            }
        }

    def test_use_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name1',
                secret_key_to_env={'password1': 'SECRET_VAR1'},
            )
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name2',
                secret_key_to_env={'password2': 'SECRET_VAR2'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env('secret-name1', {'password1': 'SECRET_VAR1'}),
                    secret_as_env('secret-name2', {'password2': 'SECRET_VAR2'}),
                ]
            }
        }

    def test_preserves_secret_as_volume(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name2', mount_path='secretpath2'
            )
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name1',
                secret_key_to_env={'password': 'SECRET_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env('secret-name1', {'password': 'SECRET_VAR'})
                ],
                'secretAsVolume': [
                    secret_as_volume('secret-name2', 'secretpath2')
                ],
            }
        }

    def test_preserves_pvc_mount(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name',
                secret_key_to_env={'password': 'SECRET_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'secretAsEnv': [
                    secret_as_env('secret-name', {'password': 'SECRET_VAR'})
                ],
            }
        }

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(secret_name_input1: str):
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name=secret_name_input1,
                secret_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        pipeline_input('secret_name_input1'), {'foo': 'CM_VAR'}
                    )
                ]
            }
        }
        reference = env_refs(lowered(my_pipeline)['comp'])['CM_VAR'][
            'secretKeyRef'
        ]
        assert reference['key'] == 'foo'
        assert reference['name'].startswith('{{inputs.parameters.')

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(secret_name_input1: str, secret_name_input2: str):
            t1 = comp()
            kubernetes.use_secret_as_env(
                t1,
                secret_name=secret_name_input1,
                secret_key_to_env={'foo': 'CM_VAR'},
            )
            kubernetes.use_secret_as_env(
                t1,
                secret_name=secret_name_input2,
                secret_key_to_env={'foo': 'CM_VAR'},
            )
            t2 = comp()
            kubernetes.use_secret_as_env(
                t2,
                secret_name=secret_name_input2,
                secret_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        pipeline_input('secret_name_input1'), {'foo': 'CM_VAR'}
                    ),
                    secret_as_env(
                        pipeline_input('secret_name_input2'), {'foo': 'CM_VAR'}
                    ),
                ]
            },
            'exec-comp-2': {
                'secretAsEnv': [
                    secret_as_env(
                        pipeline_input('secret_name_input2'), {'foo': 'CM_VAR'}
                    )
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.use_secret_as_env(
                t1, secret_name=t2.output, secret_key_to_env={'foo': 'CM_VAR'}
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    )
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            kubernetes.use_secret_as_env(
                t1, secret_name=t2.output, secret_key_to_env={'foo': 'CM_VAR'}
            )
            kubernetes.use_secret_as_env(
                t1, secret_name=t3.output, secret_key_to_env={'foo': 'CM_VAR'}
            )
            t4 = comp()
            kubernetes.use_secret_as_env(
                t4, secret_name=t2.output, secret_key_to_env={'foo': 'CM_VAR'}
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsEnv': [
                    secret_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    ),
                    secret_as_env(
                        task_output('comp-with-output-2'), {'foo': 'CM_VAR'}
                    ),
                ]
            },
            'exec-comp-2': {
                'secretAsEnv': [
                    secret_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    )
                ]
            },
        }


class TestEnsureChannelInputPropagation:
    """PipelineParameterChannel values used in Kubernetes settings register in
    ``task.channel_inputs`` so sub-DAG propagation sees them."""

    def test_pipeline_param_added_to_channel_inputs(self):
        @dsl.pipeline
        def my_pipeline(secret_name: str):
            task = comp()
            initial_count = len(task.channel_inputs)
            kubernetes.use_secret_as_env(
                task, secret_name=secret_name, secret_key_to_env={'key': 'VAR'}
            )
            assert len(task.channel_inputs) == initial_count + 1
            assert secret_name.pattern in {
                channel.pattern for channel in task.channel_inputs
            }

    def test_duplicate_pipeline_param_not_added_twice(self):
        @dsl.pipeline
        def my_pipeline(secret_name: str):
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name=secret_name,
                secret_key_to_env={'key1': 'VAR1'},
            )
            count_after_first = len(task.channel_inputs)
            kubernetes.use_secret_as_volume(
                task, secret_name=secret_name, mount_path='/mnt/secret'
            )
            assert len(task.channel_inputs) == count_after_first

    def test_string_input_does_not_add_channel_inputs(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            initial_count = len(task.channel_inputs)
            kubernetes.use_secret_as_env(
                task,
                secret_name='literal-secret',
                secret_key_to_env={'key': 'VAR'},
            )
            assert len(task.channel_inputs) == initial_count

    def test_task_output_added_to_channel_inputs(self):
        @dsl.pipeline
        def my_pipeline():
            name_task = comp_with_output()
            task = comp()
            initial_count = len(task.channel_inputs)
            kubernetes.use_secret_as_env(
                task,
                secret_name=name_task.output,
                secret_key_to_env={'key': 'VAR'},
            )
            assert len(task.channel_inputs) == initial_count + 1


class TestUseConfigMapAsVolume:
    def test_use_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name', mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [config_map_as_volume('cm-name', 'cmpath')]
            }
        }
        template = lowered(my_pipeline)['comp']
        assert mounted(template)['cmpath'] == {
            'configMap': {'name': 'cm-name', 'optional': False}
        }
        assert mount_options(template, 'cmpath') == {'readOnly': True}

    def test_use_one_optional_true(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_volume(
                task,
                config_map_name='cm-name',
                mount_path='cmpath',
                optional=True,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume('cm-name', 'cmpath', optional=True)
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp'])['cmpath'] == {
            'configMap': {'name': 'cm-name', 'optional': True}
        }

    def test_use_one_optional_false(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_volume(
                task,
                config_map_name='cm-name',
                mount_path='cmpath',
                optional=False,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [config_map_as_volume('cm-name', 'cmpath')]
            }
        }

    def test_use_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name1', mount_path='cmpath1'
            )
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name2', mount_path='cmpath2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume('cm-name1', 'cmpath1'),
                    config_map_as_volume('cm-name2', 'cmpath2'),
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp']) == {
            'cmpath1': {'configMap': {'name': 'cm-name1', 'optional': False}},
            'cmpath2': {'configMap': {'name': 'cm-name2', 'optional': False}},
        }

    def test_preserves_config_map_as_env(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name1',
                config_map_key_to_env={'foo': 'CM_VAR'},
            )
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name2', mount_path='cmpath2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env('cm-name1', {'foo': 'CM_VAR'})
                ],
                'configMapAsVolume': [
                    config_map_as_volume('cm-name2', 'cmpath2')
                ],
            }
        }

    def test_alongside_pvc_mount(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name', mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'configMapAsVolume': [
                    config_map_as_volume('cm-name', 'cmpath')
                ],
            }
        }
        assert mounted(lowered(my_pipeline)['comp']) == {
            'path': {'persistentVolumeClaim': {'claimName': 'pvc-name'}},
            'cmpath': {'configMap': {'name': 'cm-name', 'optional': False}},
        }

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(cm_name_input_1: str):
            task = comp()
            kubernetes.use_config_map_as_volume(
                task, config_map_name=cm_name_input_1, mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        pipeline_input('cm_name_input_1'), 'cmpath'
                    )
                ]
            }
        }
        source = mounted(lowered(my_pipeline)['comp'])['cmpath']['configMap']
        assert source['name'].startswith('{{inputs.parameters.')

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(cm_name_input_1: str, cm_name_input_2: str):
            t1 = comp()
            kubernetes.use_config_map_as_volume(
                t1, config_map_name=cm_name_input_1, mount_path='cmpath'
            )
            kubernetes.use_config_map_as_volume(
                t1, config_map_name=cm_name_input_2, mount_path='cmpath'
            )
            t2 = comp()
            kubernetes.use_config_map_as_volume(
                t2, config_map_name=cm_name_input_2, mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        pipeline_input('cm_name_input_1'), 'cmpath'
                    ),
                    config_map_as_volume(
                        pipeline_input('cm_name_input_2'), 'cmpath'
                    ),
                ]
            },
            'exec-comp-2': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        pipeline_input('cm_name_input_2'), 'cmpath'
                    )
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.use_config_map_as_volume(
                t1, config_map_name=t2.output, mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        task_output('comp-with-output'), 'cmpath'
                    )
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            kubernetes.use_config_map_as_volume(
                t1, config_map_name=t2.output, mount_path='cmpath'
            )
            kubernetes.use_config_map_as_volume(
                t1, config_map_name=t3.output, mount_path='cmpath'
            )
            t4 = comp()
            kubernetes.use_config_map_as_volume(
                t4, config_map_name=t2.output, mount_path='cmpath'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        task_output('comp-with-output'), 'cmpath'
                    ),
                    config_map_as_volume(
                        task_output('comp-with-output-2'), 'cmpath'
                    ),
                ]
            },
            'exec-comp-2': {
                'configMapAsVolume': [
                    config_map_as_volume(
                        task_output('comp-with-output'), 'cmpath'
                    )
                ]
            },
        }


class TestUseConfigMapAsEnv:
    def test_use_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name',
                config_map_key_to_env={'foo': 'FOO', 'bar': 'BAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env('cm-name', {'foo': 'FOO', 'bar': 'BAR'})
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp']) == {
            'FOO': {
                'configMapKeyRef': {
                    'name': 'cm-name',
                    'key': 'foo',
                    'optional': False,
                }
            },
            'BAR': {
                'configMapKeyRef': {
                    'name': 'cm-name',
                    'key': 'bar',
                    'optional': False,
                }
            },
        }

    def test_use_one_optional_true(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name',
                config_map_key_to_env={'foo': 'FOO', 'bar': 'BAR'},
                optional=True,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env(
                        'cm-name', {'foo': 'FOO', 'bar': 'BAR'}, optional=True
                    )
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp'])['FOO']['configMapKeyRef'][
            'optional'
        ]

    def test_use_one_optional_false(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name',
                config_map_key_to_env={'foo': 'FOO', 'bar': 'BAR'},
                optional=False,
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env('cm-name', {'foo': 'FOO', 'bar': 'BAR'})
                ]
            }
        }

    def test_use_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name1',
                config_map_key_to_env={'foo1': 'CM_VAR1'},
            )
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name2',
                config_map_key_to_env={'foo2': 'CM_VAR2'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env('cm-name1', {'foo1': 'CM_VAR1'}),
                    config_map_as_env('cm-name2', {'foo2': 'CM_VAR2'}),
                ]
            }
        }

    def test_preserves_config_map_as_volume(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_config_map_as_volume(
                task, config_map_name='cm-name2', mount_path='cmpath2'
            )
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name1',
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env('cm-name1', {'foo': 'CM_VAR'})
                ],
                'configMapAsVolume': [
                    config_map_as_volume('cm-name2', 'cmpath2')
                ],
            }
        }

    def test_preserves_pvc_mount(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')
            kubernetes.use_config_map_as_env(
                task,
                config_map_name='cm-name',
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'configMapAsEnv': [
                    config_map_as_env('cm-name', {'foo': 'CM_VAR'})
                ],
            }
        }

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(cm_name_input_1: str):
            task = comp()
            kubernetes.use_config_map_as_env(
                task,
                config_map_name=cm_name_input_1,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env(
                        pipeline_input('cm_name_input_1'), {'foo': 'CM_VAR'}
                    )
                ]
            }
        }
        reference = env_refs(lowered(my_pipeline)['comp'])['CM_VAR'][
            'configMapKeyRef'
        ]
        assert reference['key'] == 'foo'
        assert reference['name'].startswith('{{inputs.parameters.')

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(cm_name_input_1: str, cm_name_input_2: str):
            t1 = comp()
            kubernetes.use_config_map_as_env(
                t1,
                config_map_name=cm_name_input_1,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )
            kubernetes.use_config_map_as_env(
                t1,
                config_map_name=cm_name_input_2,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )
            t2 = comp()
            kubernetes.use_config_map_as_env(
                t2,
                config_map_name=cm_name_input_2,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env(
                        pipeline_input('cm_name_input_1'), {'foo': 'CM_VAR'}
                    ),
                    config_map_as_env(
                        pipeline_input('cm_name_input_2'), {'foo': 'CM_VAR'}
                    ),
                ]
            },
            'exec-comp-2': {
                'configMapAsEnv': [
                    config_map_as_env(
                        pipeline_input('cm_name_input_2'), {'foo': 'CM_VAR'}
                    )
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.use_config_map_as_env(
                t1,
                config_map_name=t2.output,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    )
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            kubernetes.use_config_map_as_env(
                t1,
                config_map_name=t2.output,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )
            kubernetes.use_config_map_as_env(
                t1,
                config_map_name=t3.output,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )
            t4 = comp()
            kubernetes.use_config_map_as_env(
                t4,
                config_map_name=t2.output,
                config_map_key_to_env={'foo': 'CM_VAR'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'configMapAsEnv': [
                    config_map_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    ),
                    config_map_as_env(
                        task_output('comp-with-output-2'), {'foo': 'CM_VAR'}
                    ),
                ]
            },
            'exec-comp-2': {
                'configMapAsEnv': [
                    config_map_as_env(
                        task_output('comp-with-output'), {'foo': 'CM_VAR'}
                    )
                ]
            },
        }
