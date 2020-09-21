import newrelic.tests.test_cases

from newrelic.api.application import application_instance
from newrelic.api.message_trace import MessageTrace
from newrelic.api.transaction import Transaction

application = application_instance()


class TestProcessResponseHeaders(newrelic.tests.test_cases.TestCase):

    def setUp(self):
        super(TestProcessResponseHeaders, self).setUp()
        self.transaction = Transaction(application)

    def test_process_response_headers_message_trace_inside_transaction(self):
        with self.transaction:
            with MessageTrace('library', 'operation',
                    'destination_type', 'destination_name') as trace:
                trace.process_response_headers([])

    def test_process_response_headers_message_trace_without_settings(self):
        with self.transaction:
            settings = self.transaction._settings
            self.transaction._settings = None
            with MessageTrace('library', 'operation',
                    'destination_type', 'destination_name') as trace:
                trace.process_response_headers([])
            self.transaction._settings = settings

    def test_process_response_headers_message_trace_without_transaction(self):
        with MessageTrace('library', 'operation', 'destination_type',
                'destination_name') as trace:
            trace.process_response_headers([])