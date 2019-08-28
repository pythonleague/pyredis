from unittest import TestCase
from unittest.mock import Mock, MagicMock, PropertyMock, call, patch

import pyredis.pool
import pyredis.exceptions
from pyredis.exceptions import *


class TestBasePoolUnit(TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)

        self.pool = pyredis.pool.BasePool()

    def test___init___default_args(self):
        self.assertEqual(self.pool.database, 0)
        self.assertIsNone(self.pool.password)
        self.assertIsNone(self.pool.encoding)
        self.assertEqual(self.pool._conn_timeout, 2)
        self.assertEqual(self.pool._read_timeout, 2)
        self.assertEqual(self.pool.pool_size, 16)
        self.assertFalse(self.pool.close_on_err)

    def test___init___custom_args(self):
        lock_mock = Mock()
        pool = pyredis.pool.BasePool(
            database=1,
            password='blubber',
            encoding='UTF-8',
            conn_timeout=23,
            read_timeout=12,
            pool_size=123,
            lock=lock_mock
        )
        self.assertEqual(pool.database, 1)
        self.assertEqual(pool.password, 'blubber')
        self.assertEqual(pool.encoding, 'UTF-8')
        self.assertEqual(pool.conn_timeout, 23)
        self.assertEqual(pool.read_timeout, 12)
        self.assertEqual(pool.pool_size, 123)
        self.assertEqual(pool._lock, lock_mock)

    def test_acquire_free(self):
        client_orig = Mock()
        self.pool._pool_free.add(client_orig)
        self.pool._lock = Mock()

        client = self.pool.acquire()
        self.assertEqual(client_orig, client)
        self.pool._lock.assert_has_calls([
            call.acquire(),
            call.release()
        ])
        self.assertNotIn(client_orig, self.pool._pool_free)
        self.assertIn(client_orig, self.pool._pool_used)

    def test_acquire_nonfree(self):
        client_orig = Mock()
        self.pool._connect = Mock()
        self.pool._connect.side_effect = [client_orig]

        self.pool._lock = Mock()

        client = self.pool.acquire()
        self.assertEqual(client_orig, client)
        self.pool._lock.assert_has_calls([
            call.acquire(),
            call.release()
        ])
        self.assertIn(client_orig, self.pool._pool_used)

    def test_acquire_exhausted(self):
        self.pool.pool_size = 1
        self.pool._pool_used.add('a Connection')

        self.pool._lock = Mock()

        self.assertRaises(pyredis.exceptions.PyRedisError, self.pool.acquire)

        self.pool._lock.assert_has_calls([
            call.acquire(),
            call.release()
        ])

    def test_release(self):
        client = Mock()
        client.closed = False
        self.pool._pool_used.add(client)

        self.pool.release(client)
        self.assertIn(client, self.pool._pool_free)
        self.assertNotIn(client, self.pool._pool_used)

    def test_release_shrink(self):
        client = Mock()
        client.closed = False
        self.pool.pool_size = 3
        self.pool._pool_used.add(client)
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_used.add(Mock())

        self.pool.release(client)
        self.assertNotIn(client, self.pool._pool_free)
        self.assertNotIn(client, self.pool._pool_used)

    def test_release_closed_without_pool_reset(self):
        conn_release = Mock()
        conn_release.closed.return_value = True
        conn1 = Mock()
        conn2 = Mock()
        self.pool._pool_free.add(conn1)
        self.pool._pool_used.add(conn2)
        self.pool._pool_used.add(conn_release)
        self.pool.release(conn_release)
        self.assertIn(conn1, self.pool._pool_free)
        self.assertEqual(self.pool._pool_free, set([conn1]))
        self.assertEqual(self.pool._pool_used, set([conn2]))

    def test_release_closed_with_pool_reset(self):
        conn_release = Mock()
        conn_release.closed.return_value = True
        conn1 = Mock()
        conn2 = Mock()
        self.pool._close_on_err = True
        self.pool._pool_free.add(conn1)
        self.pool._pool_used.add(conn2)
        self.pool._pool_used.add(conn_release)
        self.pool.release(conn_release)
        conn1.close.assert_called_with()
        self.assertEqual(self.pool._pool_free, set())
        self.assertEqual(self.pool._pool_used, set())

    def test_release_closed_after_pool_reset(self):
        conn_release = Mock()
        conn_release.closed.return_value = True
        conn1 = Mock()
        conn2 = Mock()
        self.pool._pool_free.add(conn1)
        self.pool._pool_used.add(conn2)
        self.pool.release(conn_release)
        self.assertIn(conn1, self.pool._pool_free)
        self.assertIn(conn2, self.pool._pool_used)
        self.assertFalse(conn1.close.called)
        self.assertFalse(conn2.close.called)

    def test_shrink_pool_can_free_all(self):
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())

        self.assertEqual(len(self.pool._pool_free), 5)
        self.pool.pool_size = 3
        self.assertEqual(len(self.pool._pool_free), 3)

    def test_shrink_pool_can_not_free_all(self):
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())
        self.pool._pool_free.add(Mock())

        self.pool._pool_used.add(Mock())
        self.pool._pool_used.add(Mock())
        self.pool._pool_used.add(Mock())
        self.pool._pool_used.add(Mock())
        self.pool._pool_used.add(Mock())

        self.assertEqual(len(self.pool._pool_free), 5)
        self.assertEqual(len(self.pool._pool_used), 5)
        self.pool.pool_size = 3
        self.assertEqual(len(self.pool._pool_free), 0)
        self.assertEqual(len(self.pool._pool_used), 5)


class TestClusterPoolUnit(TestCase):
    def setUp(self):
        client_patcher = patch('pyredis.pool.ClusterClient', autospeck=True)
        self.client_mock = client_patcher.start()

        self.client_mock_inst = Mock()
        self.client_mock.return_value = self.client_mock_inst

        map_patcher = patch('pyredis.pool.ClusterMap', autospeck=True)
        self.map_mock = map_patcher.start()

        self.map_mock_inst = Mock()
        self.map_mock.return_value = self.map_mock_inst

        self.addCleanup(patch.stopall)

        self.pool = pyredis.pool.ClusterPool(seeds=[('seed1', 12345), ('seed2', 12345), ('seed3', 12345)],
                                             password='blubber')

    def test___init__(self):
        self.map_mock.assert_called_with(seeds=[('seed1', 12345), ('seed2', 12345), ('seed3', 12345)],
                                         password='blubber')
        self.assertEqual(self.pool._map, self.map_mock_inst)
        self.assertFalse(self.pool.slave_ok)

    def test___init__slave_ok_true(self):
        self.pool = pyredis.pool.ClusterPool(seeds=[('seed1', 12345), ('seed2', 12345), ('seed3', 12345)], slave_ok=True)
        self.map_mock.assert_called_with(seeds=[('seed1', 12345), ('seed2', 12345), ('seed3', 12345)], password=None)
        self.assertEqual(self.pool._map, self.map_mock_inst)
        self.assertTrue(self.pool.slave_ok)

    def test__connect(self):
        client = self.pool._connect()
        self.client_mock.assert_called_with(
            conn_timeout=2,
            password='blubber',
            read_timeout=2,
            cluster_map=self.pool._map,
            encoding=None,
            slave_ok=False,
            database=0)
        self.assertEqual(self.client_mock_inst, client)


class TestHashPoolUnit(TestCase):
    def setUp(self):
        client_patcher = patch('pyredis.pool.HashClient', autospeck=True)
        self.client_mock = client_patcher.start()
        self.addCleanup(patch.stopall)
        self.buckets = [('localhost', 7001), ('localhost', 7002), ('localhost', 7003)]

        self.pool = pyredis.pool.HashPool(buckets=self.buckets)

    def test___init__(self):
        self.assertEqual(self.pool.buckets, self.buckets)
        self.assertTrue(self.pool._cluster)

    def test__connect(self):
        client_mock = Mock()
        self.client_mock.return_value = client_mock
        client = self.pool._connect()
        self.client_mock.assert_called_with(
            buckets=self.pool.buckets,
            database=self.pool.database,
            password=self.pool.password,
            encoding=self.pool.encoding,
            conn_timeout=self.pool.conn_timeout,
            read_timeout=self.pool.read_timeout
        )
        self.assertEqual(client, client_mock)


class TestPoolUnit(TestCase):
    def setUp(self):
        client_patcher = patch('pyredis.pool.Client', autospeck=True)
        self.client_mock = client_patcher.start()
        self.addCleanup(patch.stopall)

        self.pool = pyredis.pool.Pool(host='localhost')

    def test___init___host(self):
        self.assertEqual(self.pool.host, 'localhost')
        self.assertEqual(self.pool.port, 6379)
        self.assertIsNone(self.pool.unix_sock)

    def test___init___host_port(self):
        pool = pyredis.pool.Pool(host='localhost', port=16379)
        self.assertEqual(pool.host, 'localhost')
        self.assertEqual(pool.port, 16379)
        self.assertIsNone(pool.unix_sock)

    def test___init___unix_sock(self):
        pool = pyredis.pool.Pool(unix_sock='/tmp/redis.sock')
        self.assertEqual(pool.unix_sock, '/tmp/redis.sock')
        self.assertIsNone(pool.host)

    def test__init___no_host_or_unix_sock(self):
        self.assertRaises(PyRedisError, pyredis.pool.Pool)

    def test__init___both_host_and_unix_sock(self):
        self.assertRaises(
            PyRedisError, pyredis.pool.Pool,
            host='localhost', unix_sock='/tmp/redis.sock')

    def test__connect(self):
        client_mock = Mock()
        self.client_mock.return_value = client_mock
        client = self.pool._connect()
        self.client_mock.assert_called_with(
            host=self.pool.host,
            port=self.pool.port,
            unix_sock=self.pool.unix_sock,
            database=self.pool.database,
            password=self.pool.password,
            encoding=self.pool.encoding,
            conn_timeout=self.pool.conn_timeout,
            read_timeout=self.pool.read_timeout
        )
        self.assertEqual(client, client_mock)


class TestSentinelPoolUnit(TestCase):
    def setUp(self):
        client_patcher = patch('pyredis.pool.Client', autospeck=True)
        self.client_mock = client_patcher.start()

        sentinelclient_patcher = patch('pyredis.pool.SentinelClient', autospeck=True)
        self.sentinelclient_mock = sentinelclient_patcher.start()

        self.sentinelclientinst_mock = Mock()
        self.sentinelclient_mock.return_value = self.sentinelclientinst_mock

        shuffle_mock = patch('pyredis.pool.shuffle', autospeck=True)
        self.shuffle_mock = shuffle_mock.start()

        self.addCleanup(patch.stopall)

    def test___init__default_args(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster')
        pool._sentinel.sentinels = [('host1', 12345)]
        self.sentinelclient_mock.assert_called_with(sentinels=[('host1', 12345)], password=None)
        self.assertEqual(pool.name, 'mymaster')
        self.assertEqual(pool.retries, 3)
        self.assertFalse(pool.slave_ok)
        self.assertEqual(pool.sentinels, [('host1', 12345)])
        self.assertEqual(pool._sentinel, self.sentinelclientinst_mock)

    def test___init__default_cust_args(self):
        pool = pyredis.pool.SentinelPool(
            sentinels=[('host1', 12345)],
            name='mymaster',
            slave_ok=True,
            retries=5,
            sentinel_password='blubber'
        )
        pool._sentinel.sentinels = [('host1', 12345)]
        self.sentinelclient_mock.assert_called_with(sentinels=[('host1', 12345)], password='blubber')
        self.assertEqual(pool.name, 'mymaster')
        self.assertEqual(pool.retries, 5)
        self.assertTrue(pool.slave_ok)
        self.assertEqual(pool.sentinels, [('host1', 12345)])
        self.assertEqual(pool._sentinel, self.sentinelclientinst_mock)

    def test__connect_master_ok_on_first_try(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster')
        pool._get_master = Mock()
        client_mock = Mock()
        pool._get_master.return_value = client_mock
        pool._get_slave = Mock()
        client = pool._connect()
        pool._get_master.assert_called_with()
        self.assertEqual(client, client_mock)

    def test__connect_master_ok_on_second_try(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster')
        pool._get_master = Mock()
        client_mock = Mock()
        pool._get_master.side_effect = [None, client_mock]
        pool._get_slave = Mock()
        client = pool._connect()
        pool._get_master.assert_has_calls([
            call(),
            call()
        ])
        self.assertEqual(client, client_mock)

    def test__connect_master_retires_exhausted(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster')
        pool._get_master = Mock()
        pool._get_master.side_effect = [None, None, None]
        pool._get_slave = Mock()
        self.assertRaises(PyRedisConnError, pool._connect)
        pool._get_master.assert_has_calls([
            call(),
            call(),
            call()
        ])

    def test__connect_slave_ok_on_first_try(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster', slave_ok=True)
        pool._get_master = Mock()
        client_mock = Mock()
        pool._get_slave = Mock()
        pool._get_slave.return_value = client_mock
        client = pool._connect()
        pool._get_slave.assert_called_with()
        self.assertEqual(client, client_mock)

    def test__connect_slave_ok_on_second_try(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster', slave_ok=True)
        pool._get_master = Mock()
        client_mock = Mock()
        pool._get_slave = Mock()
        pool._get_slave.side_effect = [None, client_mock]
        client = pool._connect()
        pool._get_slave.assert_has_calls([
            call(),
            call()
        ])
        self.assertEqual(client, client_mock)

    def test__connect_slave_retires_exhausted(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster', slave_ok=True)
        pool._get_master = Mock()
        pool._get_slave = Mock()
        pool._get_slave.side_effect = [None, None, None]
        self.assertRaises(PyRedisConnError, pool._connect)
        pool._get_slave.assert_has_calls([
            call(),
            call(),
            call()
        ])

    def test__get_client(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster', slave_ok=True)
        client_mock = Mock()
        self.client_mock.return_value = client_mock
        client = pool._get_client('host1', 12345)
        self.client_mock.assert_called_with(
            read_timeout=2,
            password=None,
            conn_timeout=2,
            host='host1',
            encoding=None,
            database=0,
            port=12345
        )
        self.assertEqual(client, client_mock)

    def test__get_master(self):
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster')
        pool._sentinel = Mock()
        pool._sentinel.get_master.return_value = (
            {
                b'ip': b'127.0.0.1',
                b'port': b'12345'
            }
        )
        client_mock = Mock()
        pool._get_client = Mock()
        pool._get_client.return_value = client_mock
        client = pool._get_master()
        pool._sentinel.get_master.assert_called_with('mymaster')
        pool._get_client.assert_called_with(b'127.0.0.1', 12345)
        self.assertEqual(client, client_mock)

    def test_get_slave(self):
        self.shuffle_mock.return_value = [
            (b'127.0.0.1', 12345),
            (b'127.0.0.2', 12345),
            (b'127.0.0.3', 12345)
        ]
        pool = pyredis.pool.SentinelPool(sentinels=[('host1', 12345)], name='mymaster', slave_ok=True)
        pool._sentinel = Mock()
        pool._sentinel.get_slaves.return_value = [
            {
                b'ip': b'127.0.0.1',
                b'port': b'12345'
            },
            {
                b'ip': b'127.0.0.2',
                b'port': b'12345'
            },
            {
                b'ip': b'127.0.0.3',
                b'port': b'12345'
            }
        ]
        client_mock1 = Mock()
        pool._get_client = Mock()
        pool._get_client.return_value = client_mock1
        client = pool._get_slave()
        self.shuffle_mock.assert_called_with(
            [
                (b'127.0.0.1', 12345),
                (b'127.0.0.2', 12345),
                (b'127.0.0.3', 12345)
            ]
        )
        pool._get_client.assert_called_with(b'127.0.0.1', 12345)
        self.assertEqual(client, client_mock1)
