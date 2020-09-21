import unittest

from newrelic.core.stats_engine import SampledDataSet


class TestSampledDataSet(unittest.TestCase):

    def test_empty_set(self):
        instance = SampledDataSet()

        self.assertEqual(list(instance), [])
        self.assertEqual(instance.capacity, 100)
        self.assertEqual(instance.num_seen, 0)

    def test_single_item(self):
        instance = SampledDataSet()

        instance.add(1)

        self.assertEqual(list(instance), [1])
        self.assertEqual(instance.num_seen, 1)

    def test_at_capacity(self):
        instance = SampledDataSet(100)

        for i in range(100):
            instance.add(i)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(sorted(instance), list(range(100)))
        self.assertEqual(instance.num_seen, 100)

    def test_over_capacity(self):
        instance = SampledDataSet(100)

        for i in range(200):
            instance.add(i)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(instance.num_seen, 200)

    def test_merge_sampled_data_set_under_capacity(self):
        a = SampledDataSet(capacity=100)
        b = SampledDataSet(capacity=100)

        count_a = 10
        count_b = 12
        for i in range(count_a):
            a.add(i)

        for i in range(count_b):
            b.add(i)

        a.merge(b)

        self.assertEqual(a.num_seen, count_a + count_b)
        self.assertEqual(a.num_seen, a.num_samples)

        samples = list(a)
        self.assertEqual(len(samples), a.num_seen)

    def test_merge_sampled_data_set_over_capacity(self):
        capacity = 100
        a = SampledDataSet(capacity=capacity)
        b = SampledDataSet(capacity=capacity)

        count_a = 110
        count_b = 200
        for i in range(count_a):
            a.add(i)

        for i in range(count_b):
            b.add(i)

        a.merge(b)

        self.assertEqual(a.num_seen, count_a + count_b)
        self.assertEqual(a.num_samples, capacity)

        samples = list(a)
        self.assertEqual(len(samples), capacity)

    def test_priority_over_capacity_dropped(self):
        x_priority = 1
        y_priority = 0

        instance = SampledDataSet(100)

        for i in range(100):
            instance.add('x', priority=x_priority)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(instance.num_seen, 100)

        # we will not add this sample 'y' because its priority
        # is smaller than all 'x' samples
        instance.add('y', priority=y_priority)
        self.assertEqual(False, instance.should_sample(y_priority))

        samples = list(instance)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(instance.num_seen, 101)
        self.assertTrue('y' not in samples)
        self.assertEqual(100, len(samples))

    def test_priority_over_capacity_kept(self):
        x_priority = 0
        y_priority = 1

        instance = SampledDataSet(100)

        for i in range(100):
            instance.add('x', priority=x_priority)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(instance.num_seen, 100)

        # this time, we should keep 'y' because
        # its priority is higher than any 'x'
        instance.add('y', priority=y_priority)
        self.assertEqual(True, instance.should_sample(y_priority))

        samples = list(instance)

        self.assertEqual(instance.num_samples, 100)
        self.assertEqual(instance.num_seen, 101)
        self.assertTrue('y' in samples)
        self.assertEqual(100, len(samples))

    def test_sampled_at_uses_heap(self):
        instance = SampledDataSet(2)

        instance.add('x', priority=3)
        instance.add('x', priority=1)

        # Dataset should now be sampling
        # priority 2 should override min priority 1
        self.assertTrue(instance.should_sample(2))

    def test_size_0(self):
        instance = SampledDataSet(0)

        instance.add('x')
        self.assertEqual(list(instance), [])

    # regression test for PYTHON-2964
    def test_incomparable_entries(self):
        instance = SampledDataSet(100)

        for i in range(102):
            instance.add({'a': i}, priority=0.5)

        self.assertEqual(100, len(list(instance)))


if __name__ == '__main__':
    unittest.main()