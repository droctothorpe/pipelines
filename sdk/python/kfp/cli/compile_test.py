# Copyright 2022 The Kubeflow Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for `dsl compile` command group in KFP CLI."""

import unittest

from kfp import dsl
from kfp.cli import compile_


class TestIsPipelineOrComponent(unittest.TestCase):
    def test_is_pipeline(self):

        @dsl.component
        def my_comp():
            pass

        @dsl.container_component
        def my_container_comp():
            return dsl.ContainerSpec(
                image='python:3.11',
                command=['echo', 'hello world'],
                args=[],
            )

        def my_func(a: str, b: int):
            pass

        @dsl.pipeline(name='my-pipeline')
        def my_pipeline(a: str, b: int):
            my_comp()

        self.assertFalse(compile_.is_pipeline_func(my_comp))
        self.assertFalse(compile_.is_pipeline_func(my_container_comp))
        self.assertFalse(compile_.is_pipeline_func(my_func))
        self.assertTrue(compile_.is_pipeline_func(my_pipeline))

    def test_is_component(self):

        @dsl.component
        def my_comp():
            pass

        @dsl.container_component
        def my_container_comp():
            return dsl.ContainerSpec(
                image='python:3.11',
                command=['echo', 'hello world'],
                args=[],
            )

        def my_func(a: str, b: int):
            pass

        @dsl.pipeline(name='my-pipeline')
        def my_pipeline(a: str, b: int):
            my_comp()

        self.assertTrue(compile_.is_component_func(my_comp))
        self.assertTrue(compile_.is_component_func(my_container_comp))
        self.assertFalse(compile_.is_component_func(my_func))
        self.assertFalse(compile_.is_component_func(my_pipeline))


if __name__ == '__main__':
    unittest.main()


class TestDisableTypeCheck(unittest.TestCase):
    """C48: stock's flag reaches ``Compiler.compile(type_check=...)``; as in
    stock, task input mismatches still raise when the module loads."""

    SOURCE = """
from kfp import dsl


@dsl.component
def step():
    pass


@dsl.pipeline(name='plain')
def pipeline():
    step()
"""

    def test_flag_is_passed_to_the_compiler(self):
        import pathlib
        import tempfile
        from unittest import mock

        from click.testing import CliRunner

        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory, 'pipeline.py')
            source.write_text(self.SOURCE)
            output = str(pathlib.Path(directory, 'pipeline.yaml'))
            for flags, expected in [
                ([], True),
                (['--disable-type-check'], False),
            ]:
                with mock.patch(
                    'kfp.compiler.Compiler.compile'
                ) as compile_mock:
                    result = CliRunner().invoke(
                        compile_.compile_,
                        ['--py', str(source), '--output', output, *flags],
                    )
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIs(
                    compile_mock.call_args.kwargs['type_check'], expected
                )
