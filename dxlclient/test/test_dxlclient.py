# -*- coding: utf-8 -*-
################################################################################
# Copyright (c) 2018 McAfee LLC - All Rights Reserved.
################################################################################

"""
Test cases for the DxlClient class
"""

# Run with python -m unittest dxlclient.test.test_dxlclient

from __future__ import absolute_import
import io
from textwrap import dedent
import time
import threading
import unittest

# pylint: disable=wrong-import-position
import pahoproxy.client as mqtt
from nose.plugins.attrib import attr
from parameterized import parameterized
from mock import Mock, patch

import dxlclient._global_settings
from dxlclient import Request
from dxlclient import Response
from dxlclient import Event
from dxlclient import ErrorResponse
from dxlclient import DxlClient
from dxlclient import DxlClientConfig
from dxlclient import Broker
from dxlclient import UuidGenerator
from dxlclient import EventCallback
from dxlclient import RequestCallback
from dxlclient import ResponseCallback
from dxlclient import DxlException, WaitTimeoutException

# pylint: disable=wildcard-import, unused-wildcard-import
from dxlclient._global_settings import *

from .base_test import BaseClientTest, builtins

# pylint: disable=missing-docstring

CONFIG_DATA_NO_CERTS_SECTION = """
[no_certs]
BrokerCertChain=certchain.pem
CertFile=certfile.pem
PrivateKey=privatekey.pk

[Brokers]
22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
"""
CONFIG_DATA_NO_CA_OPTION = """
[Certs]
CertFile=certfile.pem
PrivateKey=privatekey.pk

[Brokers]
22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
"""
CONFIG_DATA_NO_CERT_OPTION = """
[Certs]
BrokerCertChain=certchain.pem
PrivateKey=privatekey.pk

[Brokers]
22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
"""
CONFIG_DATA_NO_PK_OPTION = """
[Certs]
BrokerCertChain=certchain.pem
CertFile=certfile.pem

[Brokers]
22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
"""
CONFIG_DATA_NO_BROKERS_SECTION = """
[Certs]
BrokerCertChain=certchain.pem
CertFile=certfile.pem
PrivateKey=privatekey.pk

22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
"""
CONFIG_DATA_NO_BROKERS_OPTION = """
[Certs]
BrokerCertChain=certchain.pem
CertFile=certfile.pem
PrivateKey=privatekey.pk

[Brokers]
"""


class DxlClientConfigTest(unittest.TestCase):
    @parameterized.expand([
        (None,),
        ("",)
    ])
    def test_config_throws_value_error_for_empty_ca_bundle(self, ca_bundle):
        self.assertRaises(ValueError, DxlClientConfig, broker_ca_bundle=ca_bundle,
                          cert_file=get_cert_file_pem(), private_key=get_dxl_private_key(), brokers=[])

    @parameterized.expand([
        (None,),
        ("",)
    ])
    def test_config_throws_value_error_for_empty_cert_file(self, cert_file):
        self.assertRaises(ValueError, DxlClientConfig,
                          cert_file=cert_file, broker_ca_bundle=get_ca_bundle_pem(), private_key=get_dxl_private_key(),
                          brokers=[])

    def test_get_fastest_broker_gets_the_fastest(self):
        semaphore = threading.Semaphore(0)
        # Mock brokers connect speed
        fast_broker = Mock()
        slow_broker = Mock()

        def connect_to_broker_slow():
            semaphore.acquire()
            time.sleep(0.1)

        def connect_to_broker_fast():
            semaphore.release()

        slow_broker._connect_to_broker = connect_to_broker_slow
        fast_broker._connect_to_broker = connect_to_broker_fast
        # Create config and add brokers
        config = DxlClientConfig(broker_ca_bundle=get_ca_bundle_pem(),
                                 cert_file=get_cert_file_pem(),
                                 private_key=get_dxl_private_key(),
                                 brokers=[])
        config.brokers.append(fast_broker)
        config.brokers.append(slow_broker)
        # Check that the returned is the fastest
        self.assertEqual(config._get_fastest_broker(), fast_broker)

    def test_get_sorted_broker_list_returns_empty_when_no_brokers(self):
        config = DxlClientConfig(broker_ca_bundle=get_ca_bundle_pem(),
                                 cert_file=get_cert_file_pem(),
                                 private_key=get_dxl_private_key(),
                                 brokers=[])
        self.assertEqual(config._get_sorted_broker_list(), [])

    def test_get_sorted_broker_list_returns_all_brokers(self):
        # Create config
        config = DxlClientConfig(broker_ca_bundle=get_ca_bundle_pem(),
                                 cert_file=get_cert_file_pem(),
                                 private_key=get_dxl_private_key(),
                                 brokers=[])
        # Create mocked brokers
        broker1 = Broker('b1host')
        broker2 = Broker('b2host')
        broker1._connect_to_broker = broker2._connect_to_broker = Mock(
            return_value=True)
        # Add them to config
        config.brokers.append(broker1)
        config.brokers.append(broker2)
        # Get all brokers
        broker_list = config._get_sorted_broker_list()
        # Check all brokers are in the list
        self.assertTrue(broker1 in broker_list)
        self.assertTrue(broker2 in broker_list)

    def test_set_config_from_file_generates_dxl_config(self):
        read_data = """
        [Certs]
        BrokerCertChain=certchain.pem
        CertFile=certfile.pem
        PrivateKey=privatekey.pk

        [Brokers]
        22cdcace-6e8f-11e5-29c0-005056aa56de=22cdcace-6e8f-11e5-29c0-005056aa56de;8883;dxl-broker-1;10.218.73.206
        """

        with patch.object(builtins, 'open',
                          return_value=io.BytesIO(
                              dedent(read_data).encode())) as mock_open, \
                patch.object(os.path, 'isfile', return_value=True):
            client_config = DxlClientConfig.create_dxl_config_from_file("mock_file")
            self.assertEqual(client_config.cert_file, "certfile.pem")
            self.assertEqual(client_config.broker_ca_bundle, "certchain.pem")
            self.assertEqual(client_config.private_key, "privatekey.pk")
            broker = client_config.brokers[0]
            self.assertEqual(broker.host_name, "dxl-broker-1")
            self.assertEqual(broker.ip_address, "10.218.73.206")
            self.assertEqual(broker.port, 8883)
            self.assertEqual(broker.unique_id, "22cdcace-6e8f-11e5-29c0-005056aa56de")
        mock_open.assert_called_with("mock_file", "rb")

    def test_set_config_wrong_file_raises_exception(self):
        with self.assertRaises(Exception):
            DxlClientConfig.create_dxl_config_from_file("this_file_doesnt_exist.cfg")

    @parameterized.expand([
        (CONFIG_DATA_NO_CERTS_SECTION,),
        (CONFIG_DATA_NO_CA_OPTION,),
        (CONFIG_DATA_NO_CERT_OPTION,),
        (CONFIG_DATA_NO_PK_OPTION,),
    ])
    def test_missing_certs_raises_exception(self, read_data):
        with patch.object(builtins, 'open',
                          return_value=io.BytesIO(
                              dedent(read_data).encode())), \
             patch.object(os.path, 'isfile', return_value=True):
            with self.assertRaises(ValueError):
                DxlClientConfig.create_dxl_config_from_file("mock_file.cfg")

    @parameterized.expand([
        (CONFIG_DATA_NO_BROKERS_SECTION,),
        (CONFIG_DATA_NO_BROKERS_OPTION,),
    ])
    def test_missing_brokers_doesnt_raise_exceptions(self, read_data):
        with patch.object(builtins, 'open',
                          return_value=io.BytesIO(
                              dedent(read_data).encode())), \
             patch.object(os.path, 'isfile', return_value=True):
            client_config = DxlClientConfig.create_dxl_config_from_file(
                "mock_file.cfg")
            self.assertEqual(len(client_config.brokers), 0)

    class CapturedBytesIO(io.BytesIO):
        def __init__(self):
            super(DxlClientConfigTest.CapturedBytesIO, self).__init__()
            self._bytes_captured = None

        @property
        def bytes_captured(self):
            return self._bytes_captured

        def write(self, bytes_to_write):
            self._bytes_captured = bytes_to_write

    def test_write_in_memory_config(self):
        expected_data = os.linesep.join([
            "[Certs]",
            "BrokerCertChain = mycabundle.pem",
            "CertFile = mycertfile.pem",
            "PrivateKey = myprivatekey.pem",
            "{}[Brokers]".format(os.linesep),
            "myid1 = myid1;8001;myhost1;10.10.100.1",
            "myid2 = myid2;8002;myhost2;10.10.100.2{}".format(os.linesep),
            "[BrokersWebSockets]",
            "myid1 = myid1;8001;myhost1;10.10.100.1",
            "myid2 = myid2;8002;myhost2;10.10.100.2{}".format(os.linesep)])
        byte_stream = self.CapturedBytesIO()
        with patch.object(builtins, 'open',
                          return_value=byte_stream) as mock_open:
            config = DxlClientConfig(
                "mycabundle.pem",
                "mycertfile.pem",
                "myprivatekey.pem",
                [Broker("myhost1", "myid1", "10.10.100.1",
                        8001),
                 Broker("myhost2", "myid2", "10.10.100.2",
                        8002)],
                [Broker("myhost1", "myid1", "10.10.100.1",
                        8001),
                 Broker("myhost2", "myid2", "10.10.100.2",
                        8002)])
            config.write("myfile.txt")
        self.assertEqual(expected_data.encode(), byte_stream.bytes_captured)
        mock_open.assert_called_with("myfile.txt", "wb")

    def test_write_modified_config(self):
        initial_data = os.linesep.join([
            "# mycerts",
            "[Certs]",
            "BrokerCertChain = abundle.crt",
            "CertFile = acertfile.crt",
            "# pk file",
            "PrivateKey = akey.key",
            "{}[Brokers]".format(os.linesep),
            "# broker 7",
            "myid7 = myid7;8007;myhost7;10.10.100.7",
            "# broker 8",
            "myid8 = myid8;8008;myhost8;10.10.100.8{}".format(os.linesep),
            "[BrokersWebSockets]{}".format(os.linesep)])

        expected_data_after_mods = os.linesep.join([
            "# mycerts",
            "[Certs]",
            "BrokerCertChain = newbundle.pem",
            "CertFile = acertfile.crt",
            "# pk file",
            "PrivateKey = newkey.pem",
            "{}[Brokers]".format(os.linesep),
            "# broker 8",
            "myid8 = myid8;8008;myhost8;10.10.100.8",
            "myid9 = myid9;8009;myhost9;10.10.100.9{}".format(os.linesep),
            "[BrokersWebSockets]{}".format(os.linesep)])

        with patch.object(builtins, 'open',
                          return_value=io.BytesIO(initial_data.encode())), \
                patch.object(os.path, 'isfile', return_value=True):
            config = DxlClientConfig.create_dxl_config_from_file(
                "mock_file.cfg")
        del config.brokers[0]
        config.broker_ca_bundle = "newbundle.pem"
        config.private_key = "newkey.pem"
        config.brokers.append(Broker("myhost9",
                                     "myid9",
                                     "10.10.100.9",
                                     8009))
        byte_stream = self.CapturedBytesIO()
        with patch.object(builtins, 'open',
                          return_value=byte_stream) as mock_open:
            config.write("newfile.txt")
        self.assertEqual(expected_data_after_mods.encode(),
                         byte_stream.bytes_captured)
        mock_open.assert_called_with("newfile.txt", "wb")


class DxlClientTest(unittest.TestCase):
    def setUp(self):
        self.config = DxlClientConfig(broker_ca_bundle=get_ca_bundle_pem(),
                                      cert_file=get_cert_file_pem(),
                                      private_key=get_dxl_private_key(),
                                      brokers=[])

        mqtt_client_patch = patch('pahoproxy.client.Client')
        mqtt_client_patch.start()

        self.client = DxlClient(self.config)
        self.client._request_manager.wait_for_response = Mock(return_value=Response(request=None))

        self.test_channel = '/test/channel'

    def tearDown(self):
        self.client._connected = False
        self.client.destroy()
        patch.stopall()

    def test_client_raises_exception_on_connect_when_already_connecting(self):
        self.client._client.connect.side_effect = Exception("An exception!")
        self.client._thread = threading.Thread(target=None)
        self.assertEqual(self.client.connected, False)
        with self.assertRaises(DxlException):
            self.client.connect()
        self.client._thread = None

    def test_client_raises_exception_on_connect_when_already_connected(self):
        self.client._client.connect.side_effect = Exception("An exception!")
        self.client._connected = True
        with self.assertRaises(DxlException):
            self.client.connect()

    # The following test is too slow
    def test_client_disconnect_doesnt_raises_exception_on_disconnect_when_disconnected(self):
        self.assertEqual(self.client.connected, False)
        self.client.disconnect()
        self.client.disconnect()

    @parameterized.expand([
        # (connect + retries) * 2 = connect_count
        (0, 2),
        (1, 4),
        (2, 6),
    ])
    def test_client_retries_defines_how_many_times_the_client_retries_connection(self, retries, connect_count):
        # Client wont' connect ;)
        self.client._client.connect = Mock(side_effect=Exception('Could not connect'))
        # No delay between retries (faster unit tests)
        self.client.config.reconnect_delay = 0
        self.client._wait_for_policy_delay = 0

        broker = Broker(host_name='localhost')
        broker._parse(UuidGenerator.generate_id_as_string() + ";9999;localhost;127.0.0.1")

        self.client.config.brokers = [broker]
        self.client.config.connect_retries = retries

        with self.assertRaises(DxlException):
            self.client.connect()
        self.assertEqual(self.client._client.connect.call_count, connect_count)

    def test_client_subscribe_adds_subscription_when_not_connected(self):
        self.client._client.subscribe = Mock(return_value=None)
        self.assertFalse(self.client.connected)

        self.client.subscribe(self.test_channel)
        self.assertTrue(self.test_channel in self.client.subscriptions)
        self.assertEqual(self.client._client.subscribe.call_count, 0)

    def test_client_unsubscribe_removes_subscription_when_not_connected(self):
        self.client._client.unsubscribe = Mock(return_value=None)
        self.assertFalse(self.client.connected)
        # Add subscription
        self.client.subscribe(self.test_channel)
        self.assertTrue(self.test_channel in self.client.subscriptions)
        # Remove subscription
        self.client.unsubscribe(self.test_channel)
        self.assertFalse(self.test_channel in self.client.subscriptions)

    def test_client_subscribe_doesnt_add_twice_same_channel(self):
        # Mock client.subscribe and is_connected
        self.client._client.subscribe = Mock(
            return_value=(mqtt.MQTT_ERR_SUCCESS, 2))
        self.client._connected = Mock(return_value=True)
        self.client._wait_for_packet_ack = Mock(return_value=None)

        # We always have the default (myself) channel
        self.assertEqual(len(self.client.subscriptions), 1)
        self.client.subscribe(self.test_channel)
        self.assertEqual(len(self.client.subscriptions), 2)
        self.client.subscribe(self.test_channel)
        self.assertEqual(len(self.client.subscriptions), 2)
        self.assertEqual(self.client._client.subscribe.call_count, 1)

    def test_client_handle_message_with_event_calls_event_callback(self):
        event_callback = EventCallback()
        event_callback.on_event = Mock()
        self.client.add_event_callback(self.test_channel, event_callback)
        # Create and process Event
        evt = Event(destination_topic=self.test_channel)._to_bytes()
        self.client._handle_message(self.test_channel, evt)
        # Check that callback was called
        self.assertEqual(event_callback.on_event.call_count, 1)
        self.client.remove_event_callback(self.test_channel, event_callback)
        self.client._handle_message(self.test_channel, evt)
        # Check that callback was not called again - because the event
        # callback was unregistered
        self.assertEqual(event_callback.on_event.call_count, 1)

    def test_client_handle_message_with_request_calls_request_callback(self):
        req_callback = RequestCallback()
        req_callback.on_request = Mock()
        self.client.add_request_callback(self.test_channel, req_callback)
        # Create and process Request
        req = Request(destination_topic=self.test_channel)._to_bytes()
        self.client._handle_message(self.test_channel, req)
        # Check that callback was called
        self.assertEqual(req_callback.on_request.call_count, 1)
        self.client.remove_request_callback(self.test_channel, req_callback)
        self.client._handle_message(self.test_channel, req)
        # Check that callback was not called again - because the request
        # callback was unregistered
        self.assertEqual(req_callback.on_request.call_count, 1)

    def test_client_handle_message_with_response_calls_response_callback(self):
        callback = ResponseCallback()
        callback.on_response = Mock()
        self.client.add_response_callback(self.test_channel, callback)
        # Create and process Response
        msg = Response(request=None)._to_bytes()
        self.client._handle_message(self.test_channel, msg)
        # Check that callback was called
        self.assertEqual(callback.on_response.call_count, 1)
        self.client.remove_response_callback(self.test_channel, callback)
        self.client._handle_message(self.test_channel, msg)
        # Check that callback was not called again - because the response
        # callback was unregistered
        self.assertEqual(callback.on_response.call_count, 1)

    def test_client_remove_call_for_unregistered_callback_does_not_error(self):
        callback = EventCallback()
        callback.on_event = Mock()
        callback2 = EventCallback()
        callback2.on_event = Mock()
        self.client.add_event_callback(self.test_channel, callback)
        self.client.add_event_callback(self.test_channel, callback2)
        self.client.remove_event_callback(self.test_channel, callback)
        self.client.remove_event_callback(self.test_channel, callback)

    def test_client_send_event_publishes_message_to_dxl_fabric(self):
        self.client._client.publish = Mock(return_value=None)
        # Create and process Request
        msg = Event(destination_topic="")
        self.client.send_event(msg)
        # Check that callback was called
        self.assertEqual(self.client._client.publish.call_count, 1)

    def test_client_send_request_publishes_message_to_dxl_fabric(self):
        self.client._client.publish = Mock(return_value=None)
        # Create and process Request
        msg = Request(destination_topic="")
        self.client._send_request(msg)
        # Check that callback was called
        self.assertEqual(self.client._client.publish.call_count, 1)

    def test_client_send_response_publishes_message_to_dxl_fabric(self):
        self.client._client.publish = Mock(return_value=None)
        # Create and process Request
        msg = Response(request=None)
        self.client.send_response(msg)
        # Check that callback was called
        self.assertEqual(self.client._client.publish.call_count, 1)

    def test_client_handles_error_response_and_fire_response_handler(self):
        self.client._fire_response = Mock(return_value=None)
        # Create and process Request
        msg = ErrorResponse(request=None, error_code=666, error_message="test message")
        payload = msg._to_bytes()
        # Handle error response message
        self.client._handle_message(self.test_channel, payload)
        # Check that message response was properly delivered to handler
        self.assertEqual(self.client._fire_response.call_count, 1)

    def test_client_subscribe_no_ack_raises_timeout(self):
        self.client._client.subscribe = Mock(
            return_value=(mqtt.MQTT_ERR_SUCCESS, 2))
        self.client._connected = Mock(return_value=True)
        with patch.object(DxlClient, '_MAX_PACKET_ACK_WAIT', 0.01):
            with self.assertRaises(WaitTimeoutException):
                self.client.subscribe(self.test_channel)

    def test_client_unsubscribe_no_ack_raises_timeout(self):
        self.client._client.subscribe = Mock(
            return_value=(mqtt.MQTT_ERR_SUCCESS, 2))
        self.client._client.unsubscribe = Mock(
            return_value=(mqtt.MQTT_ERR_SUCCESS, 3))
        self.client._connected = Mock(return_value=True)
        original_wait_packet_acked_func = self.client._wait_for_packet_ack
        self.client._wait_for_packet_ack = Mock(return_value=None)
        self.client.subscribe(self.test_channel)
        self.client._wait_for_packet_ack = original_wait_packet_acked_func
        with patch.object(DxlClient, '_MAX_PACKET_ACK_WAIT', 0.01):
            with self.assertRaises(WaitTimeoutException):
                self.client.unsubscribe(self.test_channel)

    # Service unit tests

    def test_client_register_service_subscribes_client_to_channel(self):
        channel = '/mcafee/service/unittest'

        # Create dummy service
        service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)

        # Add topics to the service
        service_info.add_topic(channel + "1", RequestCallback())
        service_info.add_topic(channel + "2", RequestCallback())
        service_info.add_topics({channel + str(i): RequestCallback()
                                 for i in range(3, 6)})

        subscriptions_before_registration = self.client.subscriptions
        expected_subscriptions_after_registration = \
            sorted(subscriptions_before_registration +
                   tuple(channel + str(i) for i in range(1, 6)))

        # Register service in client
        self.client.register_service_async(service_info)
        # Check subscribed channels
        subscriptions_after_registration = self.client.subscriptions

        self.assertEqual(expected_subscriptions_after_registration,
                         sorted(subscriptions_after_registration))

    def test_client_wont_register_the_same_service_twice(self):
        service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)

        # Register service in client
        self.client.register_service_async(service_info)
        with self.assertRaises(dxlclient.DxlException):
            # Re-register service
            self.client.register_service_async(service_info)

    def test_client_register_service_sends_register_request_to_broker(self):
        service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)

        self.client._send_request = Mock(return_value=True)
        self.client._connected = Mock(return_value=True)

        # Register service in client
        self.client.register_service_async(service_info)
        time.sleep(2)
        # Check that method has been called
        self.assertTrue(self.client._send_request.called)

    def test_client_register_service_unsubscribes_client_to_channel(self):
        channel1 = '/mcafee/service/unittest/one'
        channel2 = '/mcafee/service/unittest/two'
        # Create dummy service
        service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)
        service_info.add_topic(channel1, RequestCallback())
        service_info.add_topic(channel2, RequestCallback())

        # Register service in client
        self.client.register_service_async(service_info)
        # Check subscribed channels
        subscriptions = self.client.subscriptions
        self.assertIn(channel1, subscriptions, "Client wasn't subscribed to service channel")
        self.assertIn(channel2, subscriptions, "Client wasn't subscribed to service channel")

        self.client.unregister_service_async(service_info)
        subscriptions = self.client.subscriptions
        self.assertNotIn(channel1, subscriptions, "Client wasn't unsubscribed to service channel")
        self.assertNotIn(channel2, subscriptions, "Client wasn't unsubscribed to service channel")

    def test_client_register_service_unsuscribes_from_channel_by_guid(self):
        channel1 = '/mcafee/service/unittest/one'
        channel2 = '/mcafee/service/unittest/two'

        # Create dummy service
        service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)
        service_info.add_topic(channel1, RequestCallback())
        service_info.add_topic(channel2, RequestCallback())

        # Create same dummy service - different object
        service_info2 = service_info = dxlclient.service.ServiceRegistrationInfo(
            service_type='/mcafee/service/unittest', client=self.client)
        service_info._service_id = service_info.service_id
        service_info.add_topic(channel1, RequestCallback())
        service_info.add_topic(channel2, RequestCallback())

        # Register service in client
        self.client.register_service_async(service_info)

        # Check subscribed channels
        subscriptions = self.client.subscriptions
        self.assertIn(channel1, subscriptions, "Client wasn't subscribed to service channel")
        self.assertIn(channel2, subscriptions, "Client wasn't subscribed to service channel")

        self.client.unregister_service_async(service_info2)
        subscriptions = self.client.subscriptions
        self.assertNotIn(channel1, subscriptions, "Client wasn't unsubscribed to service channel")
        self.assertNotIn(channel2, subscriptions, "Client wasn't unsubscribed to service channel")


@attr('system')
class DxlClientSystemClientTest(BaseClientTest):

    def test_client_connects_to_broker_and_sets_current_broker(self):

        with self.create_client() as client:
            broker_ids = [broker.unique_id for broker in client.config.brokers]
            client.connect()
            self.assertTrue(client.connected)
            self.assertIn(client.current_broker.unique_id, broker_ids)

    def test_client_raises_exception_when_cannot_sync_connect_to_broker(self):

        with self.create_client(max_retries=0) as client:
            broker = Broker("localhost", UuidGenerator.generate_id_as_string(),
                            "127.0.0.255", 58883)
            client._config.brokers = [broker]
            client._config.websocket_brokers = [broker]

            with self.assertRaises(DxlException):
                client.connect()

    def test_client_receives_event_on_topic_only_after_subscribe(self):
        """
        The idea of this test is to send an event to a topic which we are not
        subscribed, so we shouldn't be notified. Then, we subscribe to that
        topic and send a new event, we should get that last one.
        """
        with self.create_client() as client:
            test_topic = '/test/whatever/' + client.config._client_id
            client.connect()
            self.assertTrue(client.connected)

            # Set request callback (use mock to easily check when it was called)
            ecallback = EventCallback()
            ecallback.on_event = Mock()
            client.add_event_callback(test_topic, ecallback, False)

            # Send event thru dxl fabric to a topic which we are *not* subscribed
            msg = Event(destination_topic=test_topic)
            client.send_event(msg)

            time.sleep(1)
            # We haven't been notified
            self.assertEqual(ecallback.on_event.call_count, 0)

            # Subscribe to topic
            client.subscribe(test_topic)

            # Send event thru dxl fabric again to that topic
            msg = Event(destination_topic=test_topic)
            client.send_event(msg)

            time.sleep(1)
            # Now we should have been notified of the event
            self.assertEqual(ecallback.on_event.call_count, 1)

    def test_client_receives_error_response_on_request_to_unknown_service(self):
        """
        The idea of this test is to send a sync request to an unknown service
        and get a "unable to locate service" error response.
        """
        with self.create_client() as client:
            test_topic = '/test/doesntexists/' + client.config._client_id
            client.connect()
            self.assertTrue(client.connected)

            # Send request thru dxl fabric to a service which doesn't exists
            msg = Request(destination_topic=test_topic)
            msg.service_id = UuidGenerator.generate_id_as_string()
            response = client.sync_request(msg, 1)

            # Check that we have an error response for our request
            self.assertTrue(isinstance(response, ErrorResponse))
            self.assertEqual(response.service_id, msg.service_id)


if __name__ == '__main__':
    unittest.main()
