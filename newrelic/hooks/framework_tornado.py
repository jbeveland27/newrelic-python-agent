from __future__ import with_statement

import logging
import sys
import weakref

from newrelic.api.application import application_instance
from newrelic.api.transaction import current_transaction
from newrelic.api.object_wrapper import ObjectWrapper, callable_name
from newrelic.api.web_transaction import WebTransaction
from newrelic.api.function_trace import FunctionTrace, wrap_function_trace

_logger = logging.getLogger(__name__)

def record_exception(transaction, exc_info):
    import tornado.web

    exc = exc_info[0]
    value = exc_info[1]

    if exc is tornado.web.HTTPError:
        if value.status_code == 404:
            return

    transaction.record_exception(*exc_info)

def request_environment(application, request):
    result = {}

    result['REQUEST_URI'] = request.uri
    result['QUERY_STRING'] = request.query

    value = request.headers.get('X-NewRelic-ID')
    if value:
        result['HTTP_X_NEWRELIC_ID'] = value

    settings = application.settings

    if not settings:
        return result

    for key in settings.include_environ:
        if key == 'REQUEST_METHOD':
            result[key] = request.method
        elif key == 'HTTP_USER_AGENT':
            value = request.headers.get('User-Agent')
            if value:
                result[key] = value
        elif key == 'HTTP_REFERER':
            value = request.headers.get('Referer')
            if value:
                result[key] = value
        elif key == 'CONTENT_TYPE':
            value = request.headers.get('Content-Type')
            if value:
                result[key] = value
        elif key == 'CONTENT_LENGTH':
            value = request.headers.get('Content-Length')
            if value:
                result[key] = value

    return result

def instrument_tornado_httpserver(module):

    def on_headers_wrapper(wrapped, instance, args, kwargs):
        assert instance is not None

        connection = instance

        # Check to see if we are being called within the context of any
        # sort of transaction. If we are, then we don't bother doing
        # anything and just call the wrapped function. This should not
        # really ever occur but check anyway.

        transaction = current_transaction()

        if transaction:
            return wrapped(*args, **kwargs)

        # Execute the wrapped function as we are only going to do
        # something after it has been called. The function doesn't
        # return anything.

        wrapped(*args, **kwargs)

        # Check to see if the connection has already been closed or the
        # request finished. The connection can be closed where request
        # content length was too big.

        if connection.stream.closed():
            return

        if connection._request_finished:
            return

        # Check to see if have already associated a transaction with
        # the request, because if we have, even if not finished, then
        # do not need to do anything.

        request = connection._request

        if request is None:
            return

        if hasattr(request, '_nr_transaction'):
            return

        # Always use the default application specified in the agent
        # configuration.

        application = application_instance()

        # We need to fake up a WSGI like environ dictionary with the
        # key bits of information we need.

        environ = request_environment(application, request)

        # Now start recording the actual web transaction. Bail out
        # though if turns out that recording transactions is not
        # enabled.

        transaction = WebTransaction(application, environ)

        if not transaction.enabled:
            return

        transaction.__enter__()

        request._nr_transaction = transaction

        request._nr_wait_function_trace = None

        # We need to add a reference to the request object in to the
        # transaction object as only able to stash the transaction
        # in a deferred. Need to use a weakref to avoid an object
        # cycle which may prevent cleanup of transaction.

        transaction._nr_current_request = weakref.ref(request)

        try:
            request._nr_wait_function_trace = FunctionTrace(
                    transaction, name='Request/Input',
                    group='Python/Tornado')

            request._nr_wait_function_trace.__enter__()
            transaction.drop_transaction()

        except:  # Catch all
            # If an error occurs assume that transaction should be
            # exited. Technically don't believe this should ever occur
            # unless our code here has an error.

            _logger.exception('Unexpected exception raised by Tornado '
                    'HTTPConnection._on_headers().')

            transaction.__exit__(*sys.exc_info())
            request._nr_transaction = None

            raise

    module.HTTPConnection._on_headers = ObjectWrapper(
            module.HTTPConnection._on_headers, None, on_headers_wrapper)

    def on_request_body_wrapper(wrapped, instance, args, kwargs):
        assert instance is not None

        request = instance._request

        # If no transaction associated with the request we can call
        # through straight away. There should also be a current function
        # trace node.

        if not hasattr(request, '_nr_transaction'):
            return wrapped(*args, **kwargs)

        if not request._nr_transaction:
            return wrapped(*args, **kwargs)

        if not request._nr_wait_function_trace:
            return wrapped(*args, **kwargs)

        # Restore the transaction.

        transaction = request._nr_transaction

        transaction.save_transaction()

        # Exit the function trace node. This should correspond to the
        # reading of the request input.

        try:
            request._nr_wait_function_trace.__exit__(None, None, None)

        finally:
            request._nr_wait_function_trace = None

        try:
            # Now call the orginal wrapped function. It will in turn
            # call the application which will ensure the transaction
            # started here is popped off.

            return wrapped(*args, **kwargs)

        except:  # Catch all
            # If an error occurs assume that transaction should be
            # exited. Technically don't believe this should ever occur
            # unless our code here has an error.

            _logger.exception('Unexpected exception raised by Tornado '
                    'HTTPConnection._on_request_body().')

            transaction.__exit__(*sys.exc_info())
            request._nr_transaction = None

            raise

    module.HTTPConnection._on_request_body = ObjectWrapper(
            module.HTTPConnection._on_request_body, None,
            on_request_body_wrapper)

    def finish_request_wrapper(wrapped, instance, args, kwargs):
        assert instance is not None

        request = instance._request

        transaction = current_transaction()

        if transaction:
            return wrapped(*args, **kwargs)

        if not hasattr(request, '_nr_transaction'):
            return wrapped(*args, **kwargs)

        transaction = request._nr_transaction

        if transaction is None:
            return wrapped(*args, **kwargs)

        transaction.save_transaction()

        try:
            result = wrapped(*args, **kwargs)

            if request._nr_wait_function_trace:
                request._nr_wait_function_trace.__exit__(None, None, None)

            transaction.__exit__(None, None, None)

        except:  # Catch all
            transaction.__exit__(*sys.exc_info())
            raise

        finally:
            request._nr_wait_function_trace = None
            request._nr_transaction = None

        return result

    module.HTTPConnection._finish_request = ObjectWrapper(
            module.HTTPConnection._finish_request, None,
            finish_request_wrapper)

    def finish_wrapper(wrapped, instance, args, kwargs):
        assert instance is not None

        request = instance

        # Call finish() method straight away if request is not even
        # associated with a transaction.

        if not hasattr(request, '_nr_transaction'):
            return wrapped(*args, **kwargs)

        # Technically we should only be able to be called here without
        # an active transaction if we are in the wait state. If we are
        # called in context of original request handler or a deferred
        # the transaction should already be registered.

        transaction = request._nr_transaction

        if request._nr_wait_function_trace:
            if current_transaction():
                _logger.debug('The Tornado request finish() method is '
                        'being called while in wait state but there is '
                        'already a current transaction.')
            else:
                transaction.save_transaction()

        elif not current_transaction():
            _logger.debug('The Tornado request finish() method is '
                    'being called from request handler or a deferred '
                    'but there is not a current transaction.')

        # If there is a current transaction, does it match that against
        # the request.

        if transaction and transaction != current_transaction():
            # This can happen when one request handler calls finish()
            # for a different request. We need to swap the current
            # transaction around and call ourselves again. When it
            # returns we need to restore things back the way they were,
            # noting that the transaction we substituted in could have
            # completed and may not longer be current in which case
            # we should not drop it.

            running_transaction = current_transaction()
            running_transaction.drop_transaction()

            transaction.save_transaction()

            try:
                return finish_wrapper(wrapped, instance, args, kwargs)

            finally:
                if current_transaction():
                    transaction.drop_transaction()
                running_transaction.save_transaction()

        # Except for case of being called when in wait state, we can't
        # actually exit the transaction at this point as may be called
        # in context of an outer function trace node.  We pop back out
        # allowing outer scope to actually exit the transaction and it
        # will pick up that request finished by seeing that the stream
        # is closed.

        if request._nr_wait_function_trace:
            # Now handle the special case where finish() was called
            # while in the wait state. We might get here through Tornado
            # itself somehow calling finish() when still waiting for a
            # deferred. If this were to occur though then the
            # transaction will not be popped if we simply marked request
            # as finished as no outer scope to see that and clean up. We
            # will thus need to end the function trace and exit the
            # transaction. We end function trace here and then the
            # transaction down below.

            try:
                complete = True

                request._nr_wait_function_trace.__exit__(None, None, None)

                with FunctionTrace(transaction, name='Request/Finish',
                        group='Python/Tornado'):
                    result = wrapped(*args, **kwargs)

                if not request.connection.stream.writing():
                    transaction.__exit__(None, None, None)

                else:
                    request._nr_wait_function_trace = FunctionTrace(
                            transaction, name='Request/Output',
                            group='Python/Tornado')

                    request._nr_wait_function_trace.__enter__()
                    transaction.drop_transaction()

                    complete = False

            except:  # Catch all
                transaction.__exit__(*sys.exc_info())
                raise

            finally:
                if complete:
                    request._nr_wait_function_trace = None
                    request._nr_transaction = None

        else:
            # This should be the case where finish() is being called in
            # the original request handler.

            try:
                with FunctionTrace(transaction, name='Request/Finish',
                        group='Python/Tornado'):
                    result = wrapped(*args, **kwargs)

            except Exception:
                raise

        return result

    module.HTTPRequest.finish = ObjectWrapper(
            module.HTTPRequest.finish, None, finish_wrapper)

def instrument_tornado_httputil(module):

    wrap_function_trace(module, 'parse_body_arguments')
    wrap_function_trace(module, 'parse_multipart_form_data')

def instrument_tornado_web(module):

    def call_wrapper(wrapped, instance, args, kwargs):
        # We have to deal with a special case here because when using
        # tornado.wsgi.WSGIApplication() to host the async API within
        # a WSGI application, Tornado will call the wrapped method via
        # the class method rather than via an instance. This means the
        # instance will be None and the self argument will actually
        # be the first argument. The args are still left intact for
        # when we call the wrapped function.

        def _request_unbound(instance, request, *args, **kwargs):
            return instance, request

        def _request_bound(request, *args, **kwargs):
            return request

        if instance is None:
            instance, request = _request_unbound(*args, **kwargs)
        else:
            request = _request_bound(*args, **kwargs)

        # If no transaction associated with request already, need to
        # create a new one. The exception is when the the ASYNC API is
        # being executed within a WSGI application, in which case a
        # transaction will already be active. For that we execute
        # straight away.

        if instance._wsgi:
            transaction = current_transaction()

            with FunctionTrace(transaction, name='Request/Process',
                    group='Python/Tornado'):
                return wrapped(*args, **kwargs)

        elif not hasattr(request, '_nr_transaction'):
            # Always use the default application specified in the agent
            # configuration.

            application = application_instance()

            # We need to fake up a WSGI like environ dictionary with the
            # key bits of information we need.

            environ = request_environment(application, request)

            # Now start recording the actual web transaction. Bail out
            # though if turns out that recording transactions is not
            # enabled.

            transaction = WebTransaction(application, environ)

            if not transaction.enabled:
                return wrapped(*args, **kwargs)

            transaction.__enter__()

            request._nr_transaction = transaction

            request._nr_wait_function_trace = None

            # We need to add a reference to the request object in to the
            # transaction object as only able to stash the transaction
            # in a deferred. Need to use a weakref to avoid an object
            # cycle which may prevent cleanup of transaction.

            transaction._nr_current_request = weakref.ref(request)

        else:
            # If there was a transaction associated with the request,
            # only continue if a transaction is active though.

            transaction = current_transaction()

            if not transaction:
                return wrapped(*args, **kwargs)

        try:
            # Call the original method in a trace object to give better
            # context in transaction traces.

            with FunctionTrace(transaction, name='Request/Process',
                    group='Python/Tornado'):
                handler = wrapped(*args, **kwargs)

            # In the case of an immediate result or an exception
            # occuring, then finish() will have been called on the
            # request already. We can't just exit the transaction in the
            # finish call however as need to still pop back up through
            # the above function trace. So if it has been flagged that
            # it is finished, which Tornado does by setting the request
            # object in the connection to None, then we exit the
            # transaction here. Otherwise we setup a function trace to
            # track wait time for deferred and manually pop the
            # transaction as being the current one for this thread.

            if handler._finished:
                if not request.connection.stream.writing():
                    transaction.__exit__(None, None, None)
                    request._nr_transaction = None

                else:
                    request._nr_wait_function_trace = FunctionTrace(
                            transaction, name='Request/Output',
                            group='Python/Tornado')

                    request._nr_wait_function_trace.__enter__()
                    transaction.drop_transaction()

            else:
                request._nr_wait_function_trace = FunctionTrace(
                        transaction, name='Callback/Wait',
                        group='Python/Tornado')

                request._nr_wait_function_trace.__enter__()
                transaction.drop_transaction()

        except:  # Catch all
            # If an error occurs assume that transaction should be
            # exited. Technically don't believe this should ever occur
            # unless our code here has an error.

            _logger.exception('Unexpected exception raised by Tornado '
                    'Application.__call__().')

            transaction.__exit__(*sys.exc_info())
            request._nr_transaction = None

            raise

        return handler

    module.Application.__call__ = ObjectWrapper(
            module.Application.__call__, None, call_wrapper)

    # Also need to wrap the method which executes the request handler.

    def execute_wrapper(wrapped, instance, args, kwargs):
        assert instance is not None

        handler = instance
        request = handler.request

        # Check to see if we are being called within the context of any
        # sort of transaction. If we are, then we don't bother doing
        # anything and just call the wrapped function. This should not
        # really ever occur but check anyway.

        transaction = current_transaction()

        if transaction is None:
            return wrapped(*args, **kwargs)

        if request.method not in handler.SUPPORTED_METHODS:
            return wrapped(*args, **kwargs)

        name = callable_name(getattr(handler, request.method.lower()))
        transaction.name_transaction(name)

        with FunctionTrace(transaction, name=name):
            return wrapped(*args, **kwargs)

    module.RequestHandler._execute = ObjectWrapper(
            module.RequestHandler._execute, None, execute_wrapper)

    def error_wrapper(wrapped, instance, args, kwargs):
        transaction = current_transaction()

        if transaction is not None:
            record_exception(transaction, sys.exc_info())

        return wrapped(*args, **kwargs)

    module.RequestHandler._handle_request_exception = ObjectWrapper(
            module.RequestHandler._handle_request_exception, None,
            error_wrapper)

    def render_wrapper(wrapped, instance, args, kwargs):
        transaction = current_transaction()

        if transaction is None:
            return wrapped(*args, **kwargs)

        name = callable_name(wrapped)
        with FunctionTrace(transaction, name=name):
            return wrapped(*args, **kwargs)

    module.RequestHandler.render = ObjectWrapper(
            module.RequestHandler.render, None, render_wrapper)
    module.RequestHandler.render_string = ObjectWrapper(
            module.RequestHandler.render_string, None, render_wrapper)

    def generate_headers_wrapper(wrapped, instance, args, kwargs):
        transaction = current_transaction()

        if transaction is None:
            return wrapped(*args, **kwargs)

        transaction._thread_utilization_start = None

        status = '%d ???' % instance.get_status()

        response_headers = instance._headers.get_all()
        additional_headers = transaction.process_response(
                status, response_headers, *args)

        for name, value in additional_headers:
            instance.add_header(name, value)

        return wrapped(*args, **kwargs)

    module.RequestHandler._generate_headers = ObjectWrapper(
            module.RequestHandler._generate_headers, None,
            generate_headers_wrapper)

    wrap_function_trace(module, 'RequestHandler.finish')

def instrument_tornado_template(module):

    def template_generate_wrapper(wrapped, instance, args, kwargs):
        transaction = current_transaction()

        if transaction is None:
            return wrapped(*args, **kwargs)

        with FunctionTrace(transaction, name=instance.name,
                group='Template/Render'):
            return wrapped(*args, **kwargs)

    module.Template.generate = ObjectWrapper(
            module.Template.generate, None, template_generate_wrapper)

    def template_generate_wrapper(wrapped, instance, args, kwargs):
        result = wrapped(*args, **kwargs)
        if result is not None:
            return 'import newrelic.agent as _nr_newrelic_agent\n' + result

    module.Template._generate_python = ObjectWrapper(
            module.Template._generate_python, None,
            template_generate_wrapper)

    def block_generate_wrapper(wrapped, instance, args, kwargs):
        def execute(writer, *args, **kwargs):
            writer.write_line('with _nr_newrelic_agent.FunctionTrace('
                    '_nr_newrelic_agent.current_transaction(), name=%r, '
                    'group="Template/Block"):' % instance.name, instance.line)
            with writer.indent():
                writer.write_line("pass", instance.line)
                return wrapped(writer, *args, **kwargs)
        return execute(*args, **kwargs)

    module._NamedBlock.generate = ObjectWrapper(
            module._NamedBlock.generate, None, block_generate_wrapper)

def instrument_tornado_stack_context(module):

    def stack_context_wrap_wrapper(wrapped, instance, args, kwargs):
        transaction = current_transaction()

        if not transaction:
            return wrapped(*args, **kwargs)

        def callback_wrapper(wrapped, instance, args, kwargs):

            if current_transaction():
                return wrapped(*args, **kwargs)

            if not hasattr(transaction, '_nr_current_request'):
                return wrapped(*args, **kwargs)

            request = transaction._nr_current_request()

            if not request:
                return wrapped(*args, **kwargs)

            if not hasattr(request, '_nr_wait_function_trace'):
                return wrapped(*args, **kwargs)

            if not request._nr_wait_function_trace:
                return wrapped(*args, **kwargs)

            transaction.save_transaction()

            if request._nr_wait_function_trace:
                request._nr_wait_function_trace.__exit__(None, None, None)

            request._nr_wait_function_trace = None

            try:
                name = callable_name(wrapped)
                with FunctionTrace(transaction, name=name):
                    return wrapped(*args, **kwargs)

            finally:
                if not request.connection.stream.writing():
                    transaction.__exit__(None, None, None)
                    request._nr_transaction = None

                else:
                    request._nr_wait_function_trace = FunctionTrace(
                            transaction, name='Request/Output',
                            group='Python/Tornado')

                    request._nr_wait_function_trace.__enter__()
                    transaction.drop_transaction()

        def _fn(fn, *args, **kwargs):
            return fn


        fn = _fn(*args, **kwargs)

        # Tornado 3.1 does with _StackContextWrapper and checks
        # for a '_wrapped' attribute instead which makes this a
        # bit more fragile.

        if hasattr(module, '_StackContextWrapper'):
            if fn is None or fn.__class__ is module._StackContextWrapper:
                return fn
        else:
            if fn is None or hasattr(fn, '_wrapped'):
                return fn

        return ObjectWrapper(fn, None, callback_wrapper)

    module.wrap = ObjectWrapper(module.wrap, None, stack_context_wrap_wrapper)

def instrument_tornado_ioloop(module):

    wrap_function_trace(module, 'IOLoop.add_handler')
    wrap_function_trace(module, 'IOLoop.add_timeout')
    wrap_function_trace(module, 'IOLoop.add_callback')

    if hasattr(module, 'PollIOLoop'):
        wrap_function_trace(module, 'PollIOLoop.add_handler')
        wrap_function_trace(module, 'PollIOLoop.add_timeout')
        wrap_function_trace(module, 'PollIOLoop.add_callback')
        wrap_function_trace(module, 'PollIOLoop.add_callback_from_signal')

def instrument_tornado_curl_httpclient(module):

    wrap_function_trace(module, 'CurlAsyncHTTPClient.fetch')

def instrument_tornado_simple_httpclient(module):

    wrap_function_trace(module, 'SimpleAsyncHTTPClient.fetch')
