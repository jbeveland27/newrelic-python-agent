import urllib3

from testing_support.fixtures import (validate_transaction_metrics,
    validate_transaction_errors)
from testing_support.external_fixtures import (cache_outgoing_headers,
    validate_cross_process_headers, insert_incoming_headers,
    validate_external_node_params)

from newrelic.agent import background_task

_test_urlopen_http_request_scoped_metrics = [
        ('External/www.example.com/urllib3/', 1)]

_test_urlopen_http_request_rollup_metrics = [
        ('External/all', 1),
        ('External/allOther', 1),
        ('External/www.example.com/all', 1),
        ('External/www.example.com/urllib3/', 1)]

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_http_request_connection_pool_urlopen',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_http_request_connection_pool_urlopen():
    pool = urllib3.HTTPConnectionPool('www.example.com')
    pool.urlopen('GET', '/index.html')

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_http_request_connection_pool_request',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_http_request_connection_pool_request():
    pool = urllib3.HTTPConnectionPool('www.example.com')
    pool.request('GET', '/index.html')

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_http_request_connection_from_url_request',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_http_request_connection_from_url_request():
    conn = urllib3.connection_from_url('www.example.com')
    conn.request('GET', '/index.html')

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_http_request_pool_manager_urlopen',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_http_request_pool_manager_urlopen():
    pool = urllib3.PoolManager(5)
    pool.urlopen('GET', 'http://www.example.com/index.html')

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_https_request_connection_pool_urlopen',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_https_request_connection_pool_urlopen():
    pool = urllib3.HTTPSConnectionPool('www.example.com')
    pool.urlopen('GET', '/index.html')

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_https_request_connection_pool_request',
        scoped_metrics=_test_urlopen_http_request_scoped_metrics,
        rollup_metrics=_test_urlopen_http_request_rollup_metrics,
        background_task=True)
@background_task()
def test_https_request_connection_pool_request():
    pool = urllib3.HTTPSConnectionPool('www.example.com')
    pool.request('GET', '/index.html')

@validate_transaction_errors(errors=[])
@background_task()
@cache_outgoing_headers
@validate_cross_process_headers
def test_urlopen_cross_process_request():
    pool = urllib3.HTTPConnectionPool('www.example.com')
    pool.urlopen('GET', '/index.html')

_test_urlopen_cross_process_response_scoped_metrics = [
        ('ExternalTransaction/www.example.com/1#2/test', 1)]

_test_urlopen_cross_process_response_rollup_metrics = [
        ('External/all', 1),
        ('External/allOther', 1),
        ('External/www.example.com/all', 1),
        ('ExternalApp/www.example.com/1#2/all', 1),
        ('ExternalTransaction/www.example.com/1#2/test', 1)]

_test_urlopen_cross_process_response_external_node_params = [
        ('cross_process_id', '1#2'),
        ('external_txn_name', 'test'),
        ('transaction_guid', '0123456789012345')]

@validate_transaction_errors(errors=[])
@validate_transaction_metrics(
        'test_urllib3:test_urlopen_cross_process_response',
        scoped_metrics=_test_urlopen_cross_process_response_scoped_metrics,
        rollup_metrics=_test_urlopen_cross_process_response_rollup_metrics,
        background_task=True)
@insert_incoming_headers
@validate_external_node_params(
        params=_test_urlopen_cross_process_response_external_node_params)
@background_task()
def test_urlopen_cross_process_response():
    pool = urllib3.HTTPConnectionPool('www.example.com')
    pool.urlopen('GET', '/')