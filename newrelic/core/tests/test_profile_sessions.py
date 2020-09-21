import unittest
import zlib
import base64
import time

from newrelic.core.profile_sessions import (
        ProfileSessionManager, ProfileSession, CallTree,
        SessionState, profile_session_manager)

def _(method_tuple):
    filename, func_name, func_line, exec_line = method_tuple
    if func_line == exec_line:
        return (filename, '@%s#%s' % (func_name, func_line), exec_line)
    else:
        return (filename, '%s#%s' % (func_name, func_line), exec_line)

def _unscramble(data):
    if data:
        return (
            zlib.decompress(base64.standard_b64decode(data)).decode('utf-8'))

class TestCallTree(unittest.TestCase):

    def setUp(self):
        self.method_a = ('file_a', 'method_a', 10, 10)
        self.method_b = ('file_b', 'method_b', 20, 20)
        self.method_c = ('file_c', 'method_c', 25, 25)
        self.method_d = ('file_d', 'method_d', 15, 15)
        self.call_tree = CallTree(self.method_a)

    def test_flatten(self):
        expected = [_(self.method_a), 0, 0, []]
        self.assertEqual(self.call_tree.flatten(), expected)

class TestProfileSession(unittest.TestCase):
    def setUp(self):
        self.method_a = ('file_a', 'method_a', 10, 10)
        self.method_b = ('file_b', 'method_b', 20, 20)
        self.method_c = ('file_c', 'method_c', 25, 25)
        self.method_d = ('file_d', 'method_d', 15, 15)

        self.stack_trace1 = [self.method_a, self.method_b, self.method_c]
        self.stack_trace2 = [self.method_a, self.method_d, self.method_c]
        self.stack_trace3 = [self.method_b, self.method_d, self.method_c]

        self.g_profile_session = ProfileSession(-1, time.time()+2)

    def test_update_call_tree(self):
        self.assertFalse(self.g_profile_session.update_call_tree('ABCD',
            self.stack_trace2), msg="Invalid call bucket.")

        self.assertTrue(self.g_profile_session.update_call_tree('REQUEST',
            self.stack_trace1))

        bucket = self.g_profile_session.call_buckets['REQUEST']
        tree = bucket.get(self.stack_trace1[0])

        self.assertEqual(len(self.g_profile_session.call_buckets['REQUEST']), 1)

        st1_expected = [_(self.method_a), 1, 0, [ [_(self.method_b), 1, 0,
            [[_(self.method_c), 1, 0, []]]] ] ]
        self.assertEqual(st1_expected, tree.flatten())

        self.assertTrue(self.g_profile_session.update_call_tree('REQUEST',
            self.stack_trace2))

        self.assertEqual(len(self.g_profile_session.call_buckets['REQUEST']), 1)

        st2_expected = [_(self.method_a), 2, 0,
                [
                    [_(self.method_b), 1, 0, [[_(self.method_c), 1, 0, []]]],
                    [_(self.method_d), 1, 0, [[_(self.method_c), 1, 0, []]]]
                ]
            ]
        self.assertEqual(st2_expected, tree.flatten())

        self.assertTrue(self.g_profile_session.update_call_tree('REQUEST',
            self.stack_trace3))

        self.assertEqual(len(self.g_profile_session.call_buckets['REQUEST']), 2)
        self.assertEqual(st2_expected, tree.flatten())

        tree = bucket.get(self.stack_trace3[0])

        st3_expected = [_(self.method_b), 1, 0, [ [_(self.method_d), 1, 0,
            [[_(self.method_c), 1, 0, []]]] ] ]
        self.assertEqual(st3_expected, tree.flatten())

    def test_generic_profiler_profile_data(self):

        self.assertEqual(self.g_profile_session.state,
                SessionState.RUNNING)

        # Try to get profile_data before the session is finished.

        prof_data = self.g_profile_session.profile_data()
        self.assertTrue(prof_data is None,
                'Profiling has not finished. Data should be None.')

        # Finish the session and then get the profile_data. We should get an
        # empty dictionary struct for the profile tree.

        self.g_profile_session.state = SessionState.FINISHED
        prof_data = self.g_profile_session.profile_data()
        self.assertTrue(_unscramble(prof_data[0][4]) == '{}',
                        'Expected {}. Instead got %s' % _unscramble(prof_data[0][4]))

        self.g_profile_session.update_call_tree('REQUEST', self.stack_trace1)
        p = self.g_profile_session.profile_data()[0]

        # profile_id
        self.assertEqual(p[0], -1)
        # start_time < stop_time
        self.assertTrue(p[1]<p[2])
        # sample_count
        self.assertEqual(p[3], 0)
        # thread_count
        self.assertEqual(p[5], 1)
        # Non-runnable thread count - always zero
        self.assertEqual(p[6], 0)
        # xray_id
        self.assertEqual(p[7], None)

        expected = '{"REQUEST":[[["file_a","@method_a#10",10],' \
                '1,0,[[["file_b","@method_b#20",20],1,0,[[["file_c",' \
                '"@method_c#25",25],1,0,[]]]]]]]}'
        self.assertEqual(_unscramble(p[4]), expected)


class TestProfileSessionManager(unittest.TestCase):

    def test_profile_session_manager_singleton(self):
        a = profile_session_manager()
        self.assertNotEqual(a, None)

        b = profile_session_manager()
        self.assertEqual(a, b)

    def test_start_full_profile_session(self):
        manager = ProfileSessionManager()

        # Create a full profile session
        self.assertTrue(manager.start_profile_session('app', -1, time.time()+1))

        fps = manager.full_profile_session
        # Check if this is created correctly.
        self.assertTrue(isinstance(fps, ProfileSession))

        # Full Profile Session must be running.
        self.assertEqual(fps.state, SessionState.RUNNING)

        # Create another full profile session while the first one is running.
        self.assertFalse(manager.start_profile_session('app', -1, time.time()+1),
                msg='Full profile session already running. This should have '
                'returned False.')

    def test_stop_profile_session(self):
        manager = ProfileSessionManager()

        manager.start_profile_session('app', -1, time.time() + 2)

        fps = manager.full_profile_session

        # Make sure none of the sessions have finished.
        self.assertEqual(manager.finished_sessions, {})

        manager.stop_profile_session('app')
        self.assertTrue(manager.full_profile_session is None)
        self.assertEqual(manager.finished_sessions['app'], [fps], msg='Full'\
                'profile session has finished.')

    def test_profile_data(self):

        manager = ProfileSessionManager()

        manager.start_profile_session('app', -1, time.time() + 2)

        fps = manager.full_profile_session

        prof_data = manager.profile_data('app')
        # For a full profile session, there should not be
        # any data until the profiler is finished
        self.assertEqual(len(list(prof_data)), 0)

        manager.stop_profile_session('app')
        prof_data = manager.profile_data('app')

        self.assertEqual(len(list(prof_data)), 1)

        prof_data = manager.profile_data('app')
        self.assertEqual(len(list(prof_data)), 0)


if __name__ == '__main__':
    unittest.main()