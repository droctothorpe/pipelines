# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Stock's kfp.kubernetes unit tests for PVC, ephemeral and emptyDir volumes,
field-path env, image pull settings, timeouts and pod metadata, ported to the
native boundary.

See ``setters_test.py`` for the approach and the shared helpers.
"""

import pytest
import yaml

from kfp import dsl, kubernetes
from kfp.kubernetes.setters_test import (
    comp,
    comp_with_output,
    env_refs,
    image_pull_secret,
    lowered,
    mount_options,
    mounted,
    pipeline_input,
    pvc_mount,
    recorded,
    secret_as_env,
    secret_as_volume,
    task_output,
)


class TestMountPVC:
    def test_mount_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')

        assert recorded(my_pipeline) == {
            'exec-comp': {'pvcMount': [pvc_mount('pvc-name', 'path')]}
        }
        template = lowered(my_pipeline)['comp']
        assert mounted(template)['path'] == {
            'persistentVolumeClaim': {'claimName': 'pvc-name'}
        }
        assert mount_options(template, 'path') == {}

    def test_mount_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path1')
            kubernetes.mount_pvc(
                task, pvc_name='other-pvc-name', mount_path='path2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [
                    pvc_mount('pvc-name', 'path1'),
                    pvc_mount('other-pvc-name', 'path2'),
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp']) == {
            'path1': {'persistentVolumeClaim': {'claimName': 'pvc-name'}},
            'path2': {'persistentVolumeClaim': {'claimName': 'other-pvc-name'}},
        }

    def test_mount_with_sub_path(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(
                task, pvc_name='pvc-name', mount_path='/data', sub_path='models'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', '/data', sub_path='models')]
            }
        }
        assert mount_options(lowered(my_pipeline)['comp'], '/data') == {
            'subPath': 'models'
        }

    def test_mount_with_empty_sub_path(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.mount_pvc(
                task, pvc_name='pvc-name', mount_path='/data', sub_path=''
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {'pvcMount': [pvc_mount('pvc-name', '/data')]}
        }
        assert mount_options(lowered(my_pipeline)['comp'], '/data') == {}

    def test_mount_preserves_secret_as_env(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_env(
                task,
                secret_name='secret-name',
                secret_key_to_env={'password': 'SECRET_VAR'},
            )
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'secretAsEnv': [
                    secret_as_env('secret-name', {'password': 'SECRET_VAR'})
                ],
            }
        }

    def test_mount_preserves_secret_as_vol(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name', mount_path='secretpath'
            )
            kubernetes.mount_pvc(task, pvc_name='pvc-name', mount_path='path')

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount('pvc-name', 'path')],
                'secretAsVolume': [
                    secret_as_volume('secret-name', 'secretpath')
                ],
            }
        }

    def test_illegal_pvc_name(self):
        @dsl.component
        def identity(string: str) -> str:
            return string

        with pytest.raises(
            ValueError,
            match=r"Argument for 'input_param' must be an instance of str, dict, or PipelineChannel. "
            r"Got unknown input type: <class 'int'>.",
        ):

            @dsl.pipeline
            def my_pipeline(string: str = 'string'):
                kubernetes.mount_pvc(
                    identity(string=string), pvc_name=1, mount_path='/path'
                )

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(pvc_name_input: str):
            task = comp()
            kubernetes.mount_pvc(
                task, pvc_name=pvc_name_input, mount_path='path'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [
                    pvc_mount(pipeline_input('pvc_name_input'), 'path')
                ]
            }
        }
        claim = mounted(lowered(my_pipeline)['comp'])['path'][
            'persistentVolumeClaim'
        ]['claimName']
        assert claim.startswith('{{inputs.parameters.')

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(pvc_name_input_1: str, pvc_name_input_2: str):
            t1 = comp()
            kubernetes.mount_pvc(
                t1, pvc_name=pvc_name_input_1, mount_path='path'
            )
            t2 = comp()
            kubernetes.mount_pvc(
                t2, pvc_name=pvc_name_input_1, mount_path='path'
            )
            kubernetes.mount_pvc(
                t2, pvc_name=pvc_name_input_2, mount_path='path'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [
                    pvc_mount(pipeline_input('pvc_name_input_1'), 'path')
                ]
            },
            'exec-comp-2': {
                'pvcMount': [
                    pvc_mount(pipeline_input('pvc_name_input_1'), 'path'),
                    pvc_mount(pipeline_input('pvc_name_input_2'), 'path'),
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.mount_pvc(t1, pvc_name=t2.output, mount_path='path')

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [pvc_mount(task_output('comp-with-output'), 'path')]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline():
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            t4 = comp_with_output()
            kubernetes.mount_pvc(t1, pvc_name=t2.output, mount_path='path1')
            t5 = comp()
            kubernetes.mount_pvc(t5, pvc_name=t3.output, mount_path='path2')
            kubernetes.mount_pvc(t5, pvc_name=t4.output, mount_path='path3')

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'pvcMount': [
                    pvc_mount(task_output('comp-with-output'), 'path1')
                ]
            },
            'exec-comp-2': {
                'pvcMount': [
                    pvc_mount(task_output('comp-with-output-2'), 'path2'),
                    pvc_mount(task_output('comp-with-output-3'), 'path3'),
                ]
            },
        }


class TestGenericEphemeralVolume:
    def test_mount_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_ephemeral_volume(
                task,
                volume_name='pvc-name',
                mount_path='path',
                access_modes=['ReadWriteOnce'],
                size='5Gi',
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'genericEphemeralVolume': [
                    {
                        'volumeName': 'pvc-name',
                        'mountPath': 'path',
                        'accessModes': ['ReadWriteOnce'],
                        'defaultStorageClass': True,
                        'size': '5Gi',
                    }
                ]
            }
        }
        claim = mounted(lowered(my_pipeline)['comp'])['path']['ephemeral'][
            'volumeClaimTemplate'
        ]
        assert claim['spec'] == {
            'accessModes': ['ReadWriteOnce'],
            'resources': {'requests': {'storage': '5Gi'}},
        }, 'The cluster default storage class must stay unset'

    def test_mount_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_ephemeral_volume(
                task,
                volume_name='pvc-name',
                mount_path='path1',
                access_modes=['ReadWriteOnce'],
                size='5Gi',
            )
            kubernetes.add_ephemeral_volume(
                task,
                volume_name='other-pvc-name',
                mount_path='path2',
                access_modes=['ReadWriteMany'],
                size='10Ti',
                storage_class_name='gp2',
                labels={'label1': 'l1'},
                annotations={'annotation1': 'a1'},
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'genericEphemeralVolume': [
                    {
                        'volumeName': 'pvc-name',
                        'mountPath': 'path1',
                        'accessModes': ['ReadWriteOnce'],
                        'defaultStorageClass': True,
                        'size': '5Gi',
                    },
                    {
                        'volumeName': 'other-pvc-name',
                        'mountPath': 'path2',
                        'accessModes': ['ReadWriteMany'],
                        'size': '10Ti',
                        'storageClassName': 'gp2',
                        'metadata': {
                            'labels': {'label1': 'l1'},
                            'annotations': {'annotation1': 'a1'},
                        },
                    },
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp'])['path2'] == {
            'ephemeral': {
                'volumeClaimTemplate': {
                    'metadata': {
                        'labels': {'label1': 'l1'},
                        'annotations': {'annotation1': 'a1'},
                    },
                    'spec': {
                        'accessModes': ['ReadWriteMany'],
                        'resources': {'requests': {'storage': '10Ti'}},
                        'storageClassName': 'gp2',
                    },
                }
            }
        }

    @pytest.mark.parametrize('bad', ['ReadWriteOnce', ''])
    def test_plain_string_access_modes_raises(self, bad):
        with pytest.raises(TypeError, match='must be a list of strings'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.add_ephemeral_volume(
                    comp(),
                    volume_name='v',
                    mount_path='/m',
                    access_modes=bad,
                    size='5Gi',
                )

    def test_access_modes_list_still_works(self):
        @dsl.pipeline
        def my_pipeline():
            kubernetes.add_ephemeral_volume(
                comp(),
                volume_name='v',
                mount_path='/m',
                access_modes=['ReadWriteOnce'],
                size='5Gi',
            )

        volume = recorded(my_pipeline)['exec-comp']['genericEphemeralVolume'][0]
        assert volume['accessModes'] == ['ReadWriteOnce']


class TestEmptyDirMounts:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.empty_dir_mount(
                task,
                volume_name='emptydir-vol-1',
                mount_path='/mnt/my_vol_1',
                medium='Memory',
                size_limit='1Gi',
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'emptyDirMounts': [
                    {
                        'medium': 'Memory',
                        'mountPath': '/mnt/my_vol_1',
                        'sizeLimit': '1Gi',
                        'volumeName': 'emptydir-vol-1',
                    }
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp'])['/mnt/my_vol_1'] == {
            'emptyDir': {'medium': 'Memory', 'sizeLimit': '1Gi'}
        }

    def test_add_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.empty_dir_mount(
                task,
                volume_name='emptydir-vol-1',
                mount_path='/mnt/my_vol_1',
                medium='Memory',
                size_limit='1Gi',
            )
            kubernetes.empty_dir_mount(
                task, volume_name='emptydir-vol-2', mount_path='/mnt/my_vol_2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'emptyDirMounts': [
                    {
                        'medium': 'Memory',
                        'mountPath': '/mnt/my_vol_1',
                        'sizeLimit': '1Gi',
                        'volumeName': 'emptydir-vol-1',
                    },
                    {
                        'mountPath': '/mnt/my_vol_2',
                        'volumeName': 'emptydir-vol-2',
                    },
                ]
            }
        }
        assert mounted(lowered(my_pipeline)['comp'])['/mnt/my_vol_2'] == {
            'emptyDir': {}
        }

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.empty_dir_mount(
                task,
                volume_name='emptydir-vol-1',
                mount_path='/mnt/my_vol_1',
                medium='Memory',
                size_limit='1Gi',
            )
            kubernetes.set_image_pull_secrets(task, ['secret-name'])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'emptyDirMounts': [
                    {
                        'medium': 'Memory',
                        'mountPath': '/mnt/my_vol_1',
                        'sizeLimit': '1Gi',
                        'volumeName': 'emptydir-vol-1',
                    }
                ],
                'imagePullSecret': [image_pull_secret('secret-name')],
            }
        }


class TestUseFieldPathAsEnv:
    RUN_NAME = "metadata.annotations['pipelines.kubeflow.org/run_name']"

    def test_use_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_field_path_as_env(
                task, env_name='KFP_RUN_NAME', field_path=self.RUN_NAME
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'fieldPathAsEnv': [
                    {'name': 'KFP_RUN_NAME', 'fieldPath': self.RUN_NAME}
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp'])['KFP_RUN_NAME'] == {
            'fieldRef': {'fieldPath': self.RUN_NAME}
        }

    def test_use_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_field_path_as_env(
                task, env_name='KFP_RUN_NAME', field_path=self.RUN_NAME
            )
            kubernetes.use_field_path_as_env(
                task, env_name='POD_NAME', field_path='metadata.name'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'fieldPathAsEnv': [
                    {'name': 'KFP_RUN_NAME', 'fieldPath': self.RUN_NAME},
                    {'name': 'POD_NAME', 'fieldPath': 'metadata.name'},
                ]
            }
        }
        assert env_refs(lowered(my_pipeline)['comp'])['POD_NAME'] == {
            'fieldRef': {'fieldPath': 'metadata.name'}
        }


class TestImagePullPolicy:
    @pytest.mark.parametrize('policy', ['Always', 'IfNotPresent', 'Never'])
    def test_policies(self, policy):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.set_image_pull_policy(task, policy)

        assert recorded(my_pipeline) == {
            'exec-comp': {'imagePullPolicy': policy}
        }
        assert (
            lowered(my_pipeline)['comp']['container']['imagePullPolicy']
            == policy
        )

    def test_invalid_policy_raises(self):
        with pytest.raises(ValueError, match='Invalid imagePullPolicy'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_image_pull_policy(comp(), 'Sometimes')


class TestImagePullSecret:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.set_image_pull_secrets(task, ['secret-name'])

        assert recorded(my_pipeline) == {
            'exec-comp': {'imagePullSecret': [image_pull_secret('secret-name')]}
        }
        patch = lowered(my_pipeline)['comp']['podSpecPatch']
        assert yaml.safe_load(patch)['imagePullSecrets'] == [
            {'name': 'secret-name'}
        ]

    def test_add_two(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.set_image_pull_secrets(
                task, ['secret-name1', 'secret-name2']
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret('secret-name1'),
                    image_pull_secret('secret-name2'),
                ]
            }
        }
        patch = lowered(my_pipeline)['comp']['podSpecPatch']
        assert yaml.safe_load(patch)['imagePullSecrets'] == [
            {'name': 'secret-name1'},
            {'name': 'secret-name2'},
        ]

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='secret-name', mount_path='/mnt/my_vol'
            )
            kubernetes.set_image_pull_secrets(task, ['secret-name'])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'secretAsVolume': [
                    secret_as_volume('secret-name', '/mnt/my_vol')
                ],
                'imagePullSecret': [image_pull_secret('secret-name')],
            }
        }

    def test_component_pipeline_input_one(self):
        @dsl.pipeline
        def my_pipeline(input_1: str):
            t1 = comp()
            kubernetes.set_image_pull_secrets(t1, [input_1])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret(pipeline_input('input_1'))
                ]
            }
        }
        patch = lowered(my_pipeline)['comp']['podSpecPatch']
        assert yaml.safe_load(patch)['imagePullSecrets'][0]['name'].startswith(
            '{{inputs.parameters.'
        )

    def test_component_pipeline_input_two(self):
        @dsl.pipeline
        def my_pipeline(input_1: str, input_2: str):
            t1 = comp()
            kubernetes.set_image_pull_secrets(t1, [input_1])
            t2 = comp()
            kubernetes.set_image_pull_secrets(t2, [input_1, input_2])
            kubernetes.set_image_pull_secrets(t2, ['another-secret'])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret(pipeline_input('input_1'))
                ]
            },
            'exec-comp-2': {
                'imagePullSecret': [
                    image_pull_secret(pipeline_input('input_1')),
                    image_pull_secret(pipeline_input('input_2')),
                    image_pull_secret('another-secret'),
                ]
            },
        }

    def test_component_upstream_input_one(self):
        @dsl.pipeline
        def my_pipeline(input_1: str):
            t1 = comp()
            t2 = comp_with_output()
            kubernetes.set_image_pull_secrets(t1, [t2.output])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret(task_output('comp-with-output'))
                ]
            }
        }

    def test_component_upstream_input_two(self):
        @dsl.pipeline
        def my_pipeline(input_1: str, input_2: str):
            t1 = comp()
            t2 = comp_with_output()
            t3 = comp_with_output()
            t4 = comp_with_output()
            kubernetes.set_image_pull_secrets(t1, [t2.output])
            t5 = comp()
            kubernetes.set_image_pull_secrets(t5, [t2.output, t3.output])
            kubernetes.set_image_pull_secrets(t5, [t4.output])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret(task_output('comp-with-output'))
                ]
            },
            'exec-comp-2': {
                'imagePullSecret': [
                    image_pull_secret(task_output('comp-with-output')),
                    image_pull_secret(task_output('comp-with-output-2')),
                    image_pull_secret(task_output('comp-with-output-3')),
                ]
            },
        }

    def test_component_pipeline_multiple_input_types(self):
        @dsl.pipeline
        def my_pipeline(input_1: str):
            t1 = comp()
            kubernetes.set_image_pull_secrets(t1, ['a_str', input_1])

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'imagePullSecret': [
                    image_pull_secret('a_str'),
                    image_pull_secret(pipeline_input('input_1')),
                ]
            }
        }

    @pytest.mark.parametrize('bad', ['my-secret', ''])
    def test_plain_string_secret_names_raises(self, bad):
        with pytest.raises(TypeError, match='must be a list'):

            @dsl.pipeline
            def my_pipeline():
                kubernetes.set_image_pull_secrets(comp(), secret_names=bad)

    def test_list_of_pipeline_parameters_still_works(self):
        @dsl.pipeline
        def my_pipeline(secret: str = 'my-secret'):
            kubernetes.set_image_pull_secrets(comp(), secret_names=[secret])

        assert len(recorded(my_pipeline)['exec-comp']['imagePullSecret']) == 1


class TestTimeout:
    def test_timeout(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.set_timeout(task, seconds=20)

        assert recorded(my_pipeline) == {
            'exec-comp': {'activeDeadlineSeconds': '20'}
        }
        assert lowered(my_pipeline)['comp']['activeDeadlineSeconds'] == 20

    def test_reset_timeout(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.set_timeout(task, seconds=20)
            kubernetes.set_timeout(task, seconds=0)

        assert recorded(my_pipeline) == {'exec-comp': {}}
        assert 'activeDeadlineSeconds' not in lowered(my_pipeline)['comp']

    def test_bad_value_timeout(self):
        with pytest.raises(
            ValueError,
            match=r'Argument for "seconds" must be an integer greater or equals to 0. Got invalid input: -20.',
        ):

            @dsl.pipeline
            def my_pipeline():
                task = comp()
                kubernetes.set_timeout(task, seconds=-20)


class TestPodMetadata:
    def test_add_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_pod_label(
                task, label_key='kubeflow.com/kfp', label_value='pipeline-node'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podMetadata': {'labels': {'kubeflow.com/kfp': 'pipeline-node'}}
            }
        }
        assert lowered(my_pipeline)['comp']['metadata']['labels'] == {
            'kubeflow.com/kfp': 'pipeline-node'
        }

    def test_add_same_one(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_pod_label(
                task, label_key='kubeflow.com/kfp', label_value='pipeline-node'
            )
            kubernetes.add_pod_label(
                task, label_key='kubeflow.com/kfp', label_value='pipeline-node2'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podMetadata': {
                    'labels': {'kubeflow.com/kfp': 'pipeline-node2'}
                }
            }
        }

    def test_add_two_and_mix(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.add_pod_label(
                task, label_key='kubeflow.com/kfp', label_value='pipeline-node'
            )
            kubernetes.add_pod_label(
                task, label_key='kubeflow.com/common', label_value='test'
            )
            kubernetes.add_pod_annotation(
                task, annotation_key='run_id', annotation_value='123456'
            )
            kubernetes.add_pod_annotation(
                task, annotation_key='experiment_id', annotation_value='234567'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podMetadata': {
                    'annotations': {
                        'run_id': '123456',
                        'experiment_id': '234567',
                    },
                    'labels': {
                        'kubeflow.com/kfp': 'pipeline-node',
                        'kubeflow.com/common': 'test',
                    },
                }
            }
        }
        metadata = lowered(my_pipeline)['comp']['metadata']
        assert metadata['labels'] == {
            'kubeflow.com/kfp': 'pipeline-node',
            'kubeflow.com/common': 'test',
        }
        assert metadata['annotations']['run_id'] == '123456'
        assert metadata['annotations']['experiment_id'] == '234567'

    def test_respects_other_configuration(self):
        @dsl.pipeline
        def my_pipeline():
            task = comp()
            kubernetes.use_secret_as_volume(
                task, secret_name='my-secret', mount_path='/mnt/my_vol'
            )
            kubernetes.add_pod_annotation(
                task, annotation_key='run_id', annotation_value='123456'
            )

        assert recorded(my_pipeline) == {
            'exec-comp': {
                'podMetadata': {'annotations': {'run_id': '123456'}},
                'secretAsVolume': [
                    secret_as_volume('my-secret', '/mnt/my_vol')
                ],
            }
        }
