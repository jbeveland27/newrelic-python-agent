import pytest
import sanic

from newrelic.core.config import global_settings
from collections import deque

from newrelic.api.application import application_instance
from newrelic.api.transaction import Transaction
from newrelic.api.external_trace import ExternalTrace

from testing_support.fixtures import (validate_transaction_metrics,
    override_application_settings, validate_transaction_errors,
    validate_transaction_event_attributes,
    override_ignore_status_codes, override_generic_settings,
    function_not_called)


BASE_METRICS = [
    ('Function/_target_application:index', 1),
    ('Function/_target_application:request_middleware', 2),
]
FRAMEWORK_METRICS = [
    ('Python/Framework/Sanic/%s' % sanic.__version__, 1),
]
BASE_ATTRS = ['response.status', 'response.headers.contentType',
        'response.headers.contentLength']

validate_base_transaction_event_attr = validate_transaction_event_attributes(
    required_params={'agent': BASE_ATTRS, 'user': [], 'intrinsic': []},
)


@validate_transaction_metrics(
    '_target_application:index',
    scoped_metrics=BASE_METRICS,
    rollup_metrics=BASE_METRICS + FRAMEWORK_METRICS,
)
@validate_base_transaction_event_attr
def test_simple_request(app):
    response = app.fetch('get', '/')
    assert response.status == 200


DT_METRICS = [
    ('Supportability/DistributedTrace/AcceptPayload/Success', 1),
]


@validate_transaction_metrics(
    '_target_application:index',
    scoped_metrics=BASE_METRICS,
    rollup_metrics=BASE_METRICS + DT_METRICS + FRAMEWORK_METRICS,
)
@validate_base_transaction_event_attr
@override_application_settings({
    'distributed_tracing.enabled': True,
})
def test_inbound_distributed_trace(app):
    transaction = Transaction(application_instance())
    dt_headers = ExternalTrace.generate_request_headers(transaction)

    response = app.fetch('get', '/', headers=dict(dt_headers))
    assert response.status == 200


@pytest.mark.parametrize('endpoint', ('error', 'write_response_error'))
def test_recorded_error(app, endpoint):
    ERROR_METRICS = [
        ('Function/_target_application:%s' % endpoint, 1),
    ]

    @validate_transaction_errors(errors=['builtins:ValueError'])
    @validate_base_transaction_event_attr
    @validate_transaction_metrics(
        '_target_application:%s' % endpoint,
        scoped_metrics=ERROR_METRICS,
        rollup_metrics=ERROR_METRICS + FRAMEWORK_METRICS,
    )
    def _test():
        if endpoint == 'write_response_error':
            with pytest.raises(ValueError):
                response = app.fetch('get', '/' + endpoint)
        else:
            response = app.fetch('get', '/' + endpoint)
            assert response.status == 500

    _test()


NOT_FOUND_METRICS = [
    ('Function/_target_application:not_found', 1),
]


@validate_transaction_metrics(
    '_target_application:not_found',
    scoped_metrics=NOT_FOUND_METRICS,
    rollup_metrics=NOT_FOUND_METRICS + FRAMEWORK_METRICS,
)
@validate_base_transaction_event_attr
@override_ignore_status_codes([404])
@validate_transaction_errors(errors=[])
def test_ignored_by_status_error(app):
    response = app.fetch('get', '/404')
    assert response.status == 404


DOUBLE_ERROR_METRICS = [
    ('Function/_target_application:zero_division_error', 1),
]


@validate_transaction_metrics(
    '_target_application:zero_division_error',
    scoped_metrics=DOUBLE_ERROR_METRICS,
    rollup_metrics=DOUBLE_ERROR_METRICS,
)
@validate_transaction_errors(
        errors=['builtins:ValueError', 'builtins:ZeroDivisionError'])
def test_error_raised_in_error_handler(app):
    # Because of a bug in Sanic versions <0.8.0, the response.status value is
    # inconsistent. Rather than assert the status value, we rely on the
    # transaction errors validator to confirm the application acted as we'd
    # expect it to.
    app.fetch('get', '/zero')


STREAMING_ATTRS = ['response.status', 'response.headers.contentType']
STREAMING_METRICS = [
    ('Function/_target_application:streaming', 1),
]


@validate_transaction_metrics(
    '_target_application:streaming',
    scoped_metrics=STREAMING_METRICS,
    rollup_metrics=STREAMING_METRICS,
)
@validate_transaction_event_attributes(
    required_params={'agent': STREAMING_ATTRS, 'user': [], 'intrinsic': []},
)
def test_streaming_response(app):
    # streaming responses do not have content-length headers
    response = app.fetch('get', '/streaming')
    assert response.status == 200


ERROR_IN_ERROR_TESTS = [
    ('/sync-error', '_target_application:sync_error',
        [('Function/_target_application:sync_error', 1),
            ('Function/_target_application:handle_custom_exception_sync', 1)],
        ['_target_application:CustomExceptionSync',
        'sanic.exceptions:SanicException']),

    ('/async-error', '_target_application:async_error',
        [('Function/_target_application:async_error', 1),
            ('Function/_target_application:handle_custom_exception_async', 1)],
        ['_target_application:CustomExceptionAsync']),
]


@pytest.mark.parametrize('url,metric_name,metrics,errors',
        ERROR_IN_ERROR_TESTS)
def test_errors_in_error_handlers(app, url, metric_name, metrics, errors):

    @validate_transaction_metrics(metric_name,
            scoped_metrics=metrics,
            rollup_metrics=metrics)
    @validate_transaction_errors(errors=errors)
    def _test():
        # Because of a bug in Sanic versions <0.8.0, the response.status value
        # is inconsistent. Rather than assert the status value, we rely on the
        # transaction errors validator to confirm the application acted as we'd
        # expect it to.
        app.fetch('get', url)

    _test()


def test_no_transaction_when_nr_disabled(app):
    settings = global_settings()

    @function_not_called('newrelic.core.stats_engine',
            'StatsEngine.record_transaction')
    @override_generic_settings(settings, {'enabled': False})
    def _test():
        app.fetch('GET', '/')

    _test()


async def async_returning_middleware(*args, **kwargs):
    from sanic.response import json
    return json({'oops': 'I returned it again'})


def sync_returning_middleware(*args, **kwargs):
    from sanic.response import json
    return json({'oops': 'I returned it again'})


def sync_failing_middleware(request):
    1 / 0


@pytest.mark.parametrize('middleware,attach_to,metric_name,transaction_name', [
    (async_returning_middleware, 'request',
        'test_application:async_returning_middleware',
        'test_application:async_returning_middleware'),
    (sync_returning_middleware, 'request',
        'test_application:sync_returning_middleware',
        'test_application:sync_returning_middleware'),
    (sync_failing_middleware, 'request',
        'test_application:sync_failing_middleware',
        'test_application:sync_failing_middleware'),
    (async_returning_middleware, 'response',
        'test_application:async_returning_middleware',
        '_target_application:index'),
])
def test_returning_middleware(app, middleware, attach_to, metric_name,
        transaction_name):

    metrics = [
        ('Function/%s' % metric_name, 1),
    ]

    @validate_transaction_metrics(
            transaction_name,
            scoped_metrics=metrics,
            rollup_metrics=metrics,
    )
    @validate_base_transaction_event_attr
    def _test():
        response = app.fetch('get', '/')
        assert response.status == 200

    original_request_middleware = deque(app.app.request_middleware)
    original_response_middleware = deque(app.app.response_middleware)
    app.app.register_middleware(middleware, attach_to)

    try:
        _test()
    finally:
        app.app.request_middleware = original_request_middleware
        app.app.response_middleware = original_response_middleware


ERROR_HANDLER_METRICS = [
    ('Function/_target_application:handle_server_error', 1),
]


@validate_transaction_metrics(
        '_target_application:handle_server_error',
        scoped_metrics=ERROR_HANDLER_METRICS,
        rollup_metrics=ERROR_HANDLER_METRICS,
)
@validate_base_transaction_event_attr
@validate_transaction_errors(errors=['sanic.exceptions:ServerError'])
def test_error_handler_transaction_naming(app):
    original_request_middleware = deque(app.app.request_middleware)
    original_response_middleware = deque(app.app.response_middleware)
    app.app.request_middleware = []
    app.app.response_middleware = []

    try:
        response = app.fetch('get', '/server-error')
        assert response.status == 500
    finally:
        app.app.request_middleware = original_request_middleware
        app.app.response_middleware = original_response_middleware
