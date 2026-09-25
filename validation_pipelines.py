"""Native-v2 acceptance fixtures for the current PR; no legacy loaders."""
from pathlib import Path
from kfp import compiler, components, dsl, kubernetes

ROOT = Path(__file__).parent
IMAGE = 'kfp-pr14478/sdk-runtime:faae297e3'

@dsl.container_component
def echo(message: str, echoed: dsl.OutputPath(str)):
    return dsl.ContainerSpec(
        image=IMAGE,
        command=['python', '-c'],
        args=['import pathlib,sys; print("V2_COMPONENT_EXPORT_LOAD_OK:",sys.argv[1],flush=True); pathlib.Path(sys.argv[2]).parent.mkdir(parents=True,exist_ok=True); pathlib.Path(sys.argv[2]).write_text(sys.argv[1])', message, echoed],
    )

compiler.Compiler().compile(echo, str(ROOT / 'echo-component.yaml'))
loaded_echo = components.load_component_from_file(str(ROOT / 'echo-component.yaml'))

@dsl.component(base_image=IMAGE, install_kfp_package=False)
def report(message: str, score: float, metrics: dsl.Output[dsl.Metrics], html: dsl.Output[dsl.HTML], data: dsl.Output[dsl.Dataset]):
    from pathlib import Path
    print('NATIVE_V2_REPORT_OK:', message, flush=True)
    metrics.log_metric('accuracy', score)
    metrics.log_metric('rows', 3)
    Path(html.path).write_text('<html><body><h1>Native v2 E2E validation</h1><p>Exported and reloaded v2 component executed successfully.</p></body></html>')
    Path(data.path).write_text('name,value\nalpha,1\nbeta,2\ngamma,3\n')
    print('ARTIFACT_AND_METRICS_WRITTEN', flush=True)

@dsl.pipeline(name='pr-14478-native-v2-e2e')
def validation_pipeline(message: str = 'September 25 validation', score: float = 0.93):
    echoed = loaded_echo(message=message)
    report(message=echoed.outputs['echoed'], score=score)

@dsl.container_component
def controlled_failure():
    return dsl.ContainerSpec(image=IMAGE, command=['sh', '-c'], args=['echo "VALIDATION_FAIL=$VALIDATION_FAIL"; if [ "$VALIDATION_FAIL" = true ]; then echo INTENTIONAL_FAILURE_FOR_RETRY; exit 1; fi; echo RETRY_RECOVERED_SUCCESSFULLY'])

@dsl.pipeline(name='pr-14478-native-retry-e2e')
def retry_pipeline():
    task = controlled_failure().set_caching_options(False)
    kubernetes.use_config_map_as_env(task, config_map_name='pr14478-e2e-retry-20260925', config_map_key_to_env={'fail':'VALIDATION_FAIL'})

@dsl.container_component
def slow_log():
    return dsl.ContainerSpec(image=IMAGE, command=['python','-u','-c'], args=['import time; print("LIVE_STREAM_FIRST_LINE",flush=True); time.sleep(45); print("LIVE_STREAM_FINAL_LINE",flush=True); time.sleep(5)'])

@dsl.pipeline(name='pr-14478-live-log-e2e')
def live_pipeline():
    slow_log().set_caching_options(False)

if __name__ == '__main__':
    compiler.Compiler().compile(validation_pipeline, str(ROOT / 'validation-pipeline.yaml'))
    compiler.Compiler().compile(retry_pipeline, str(ROOT / 'retry-pipeline.yaml'))
    compiler.Compiler().compile(live_pipeline, str(ROOT / 'live-pipeline.yaml'))
    legacy = 'name: old\nimplementation:\n  container:\n    image: alpine\n'
    try:
        components.load_component_from_text(legacy)
    except ValueError as error:
        assert 'PipelineSpec IR' in str(error)
        (ROOT/'evidence/legacy-loader-rejected.txt').write_text(str(error)+'\n')
    else:
        raise AssertionError('Legacy component unexpectedly accepted')
    print('Compiled native component export/load, metrics/artifacts, retry and streaming pipelines. Legacy format rejected.')
