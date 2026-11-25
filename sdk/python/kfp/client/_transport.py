# Copyright 2026 The Kubeflow Authors
# SPDX-License-Identifier: Apache-2.0
"""Authenticated native resource transport behind the public SDK facade."""

import os
import re
from urllib.parse import urlsplit

import requests

from kfp.server_api import ApiException


class NativeTransport:
    def __init__(
        self, configuration, cookies=None, header_name=None, header_value=None
    ):
        self.configuration = configuration
        self.kubernetes_host = getattr(
            configuration, '_native_kubernetes_host', None
        )
        self.argo_server = getattr(configuration, '_native_argo_server', None)
        self.argo_verify = getattr(configuration, '_native_argo_verify', True)
        self.session = requests.Session()
        # The Client's explicit configuration owns auth/proxy/TLS; ambient .netrc
        # credentials must not replace its bearer token.
        self.session.trust_env = False
        if isinstance(cookies, str):
            self.session.headers['Cookie'] = cookies
        elif cookies is not None:
            self.session.cookies.update(cookies)
        if header_name and header_value:
            self.session.headers[header_name] = header_value
        if configuration.proxy:
            self.session.proxies.update(
                {'http': configuration.proxy, 'https': configuration.proxy}
            )

    def request(
        self, method, path, *, body=None, params=None, accept='application/json'
    ):
        if (
            not path.startswith(('/argo/', '/kubernetes/'))
            or urlsplit(path).netloc
        ):
            raise ValueError(
                'Native SDK requests must target the configured resource API.'
            )
        configuration = self.configuration
        url = configuration.host.rstrip('/') + path
        argo = False
        if self.kubernetes_host:
            if path.startswith('/kubernetes/'):
                url = self.kubernetes_host.rstrip('/') + path.removeprefix(
                    '/kubernetes'
                )
            elif path == '/argo/api/v1/info' and not self.argo_server:
                # Without Argo Server the probe is the Kubernetes API's
                # discovery document for the Argo group.
                url = (
                    self.kubernetes_host.rstrip('/')
                    + '/apis/argoproj.io/v1alpha1'
                )
            else:
                resource = re.fullmatch(
                    r'/argo/api/v1/(workflows|workflow-templates|cron-workflows)/([^/]+)(/[^/]+)?',
                    path,
                )
                if resource:
                    kind, namespace, name = resource.groups()
                    url = (
                        self.kubernetes_host.rstrip('/')
                        + f'/apis/argoproj.io/v1alpha1/namespaces/{namespace}/{kind.replace("-", "")}'
                        + (name or '')
                    )
                    if body is not None:
                        key = {
                            'workflows': 'workflow',
                            'workflow-templates': 'template',
                            'cron-workflows': 'cronWorkflow',
                        }[kind]
                        body = body.get(key, body)
                    if params:
                        params = {
                            key.removeprefix('listOptions.'): value
                            for key, value in params.items()
                        }
                elif self.argo_server:
                    # Engine-only routes (the archive) go to Argo Server itself.
                    url = self.argo_server + path.removeprefix('/argo')
                    argo = True
        authorization = configuration.get_api_key_with_prefix('authorization')
        headers = {'Accept': accept}
        if authorization:
            headers['Authorization'] = authorization
        elif configuration.username is not None:
            headers['Authorization'] = configuration.get_basic_auth_token()
        elif argo and os.environ.get('ARGO_TOKEN'):
            # A certificate kubeconfig carries no token Argo Server can use;
            # the Argo CLI's own token variable fills that gap and nothing else.
            headers['Authorization'] = os.environ['ARGO_TOKEN']
        verify = (
            (configuration.ssl_ca_cert or True)
            if configuration.verify_ssl
            else False
        )
        if argo:
            verify = self.argo_verify
        cert = None
        if configuration.cert_file and not argo:
            cert = (
                (configuration.cert_file, configuration.key_file)
                if configuration.key_file
                else configuration.cert_file
            )
        try:
            response = self.session.request(
                method,
                url,
                json=body,
                params=params,
                headers=headers,
                verify=verify,
                cert=cert,
                timeout=60,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise ApiException(status=0, reason=str(error)) from error
        if not 200 <= response.status_code < 300:
            error = ApiException(
                status=response.status_code, reason=response.reason
            )
            error.body = response.text
            error.headers = response.headers
            raise error
        if not response.content:
            return {}
        return response.json()

    def collection(
        self, path, *, params=None, kubernetes=False, metadata_only=False
    ):
        if metadata_only and not kubernetes:
            raise ValueError(
                'Metadata-only collection requires a Kubernetes resource API.'
            )
        request_options = (
            {
                'accept': 'application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1,application/json;q=0.9'
            }
            if metadata_only
            else {}
        )
        params = dict(params or {})
        params['limit' if kubernetes else 'listOptions.limit'] = 100
        key = 'continue' if kubernetes else 'listOptions.continue'
        seen, items = set(), []
        while True:
            page = self.request('GET', path, params=params, **request_options)
            items.extend(page.get('items') or [])
            token = (page.get('metadata') or {}).get('continue')
            if not token:
                return items
            if token in seen:
                raise ApiException(
                    status=500,
                    reason='The resource API repeated a continuation token.',
                )
            seen.add(token)
            params[key] = token
