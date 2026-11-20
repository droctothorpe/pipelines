# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""The upstream "hello world" integration journey's pipeline: four tasks with a
visible description, parameters and logs."""

from kfp import dsl


@dsl.component
def greet(name: str) -> str:
    message = 'Hello, ' + name
    print(message)
    return message


@dsl.component
def shout(message: str) -> str:
    print(message.upper())
    return message.upper()


@dsl.component
def count(message: str) -> int:
    print(len(message))
    return len(message)


@dsl.component
def summarize(upper: str, length: int) -> str:
    print(upper, length)
    return f'{upper} ({length})'


@dsl.pipeline(
    name='helloworld-ui', description='A four task hello world pipeline.'
)
def pipeline(name: str = 'world'):
    greeting = greet(name=name)
    upper = shout(message=greeting.output)
    length = count(message=greeting.output)
    summarize(upper=upper.output, length=length.output)
