# -*- coding: utf-8 -*-
################################################################################
# Copyright (c) 2018 McAfee LLC - All Rights Reserved.
################################################################################

"""
Test cases for the Broker class
"""

# Run with python -m unittest dxlclient.test.test_broker

from __future__ import absolute_import
import unittest
import socket
from mock import patch, ANY
from nose.tools import raises
from parameterized import parameterized

from dxlclient import Broker
from dxlclient.exceptions import MalformedBrokerUriException

# pylint: disable=missing-docstring


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.socket_mock = patch('socket.socket').start()
        self.connection_mock = patch('socket.create_connection').start()
        self.connection_mock.return_value = self.socket_mock
        self.broker = Broker(host_name='localhost')

    def tearDown(self):
        patch.stopall()

    @parameterized.expand([
        ("",),
        ("a ; "),
    ])
    @raises(MalformedBrokerUriException)
    def test_parse_string_with_invalid_port_raises_exception(self, unique_id):
        self.broker._parse(unique_id + "b; [c] ")

    @parameterized.expand([
        ("",),
        ("a ; "),
    ])
    @raises(MalformedBrokerUriException)
    def test_parse_string_without_hostname_raises_exception(self, unique_id):
        self.broker._parse(unique_id + "b")

    @parameterized.expand([
        ("",),
        ("a ; "),
    ])
    @raises(MalformedBrokerUriException)
    def test_parse_string_with_empty_hostname_raises_exception(self, unique_id):
        self.broker._parse(unique_id + "b;")

    @parameterized.expand([
        ("",),
        ("a ;"),
    ])
    @raises(MalformedBrokerUriException)
    def test_parse_string_with_port_out_of_range_raises_exception(self, unique_id):
        self.broker._parse(unique_id + "65536; [c] ")

    def test_parse_string_valid_with_unique_id_but_no_ip_address(self):
        self.broker._parse("a ; 8883; [c] ")
        self.assertEqual("a", self.broker.unique_id)
        self.assertEqual(8883, self.broker.port)
        self.assertEqual("c", self.broker.host_name)
        self.assertIsNone(self.broker.ip_address)

    def test_parse_string_valid_with_unique_id_and_ip_address(self):
        self.broker._parse("a ; 8883; [c];10.0.0.1 ")
        self.assertEqual("a", self.broker.unique_id)
        self.assertEqual(8883, self.broker.port)
        self.assertEqual("c", self.broker.host_name)
        self.assertEqual("10.0.0.1", self.broker.ip_address)

    def test_parse_string_valid_without_unique_id_or_ip_address(self):
        self.broker._parse("8883; [c] ")
        self.assertEqual("", self.broker.unique_id)
        self.assertEqual(8883, self.broker.port)
        self.assertEqual("c", self.broker.host_name)
        self.assertIsNone(self.broker.ip_address)

    def test_parse_string_valid_with_ip_address_but_no_unique_id(self):
        self.broker._parse("8883; [c];10.0.0.1 ")
        self.assertEqual("", self.broker.unique_id)
        self.assertEqual(8883, self.broker.port)
        self.assertEqual("c", self.broker.host_name)
        self.assertEqual("10.0.0.1", self.broker.ip_address)

    def test_parse_url_valid_with_host_name(self):
        broker = Broker.parse("mybroker")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("mybroker", broker.host_name)

    def test_parse_url_valid_with_host_name_and_port(self):
        broker = Broker.parse("mybroker:8993")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("mybroker", broker.host_name)
        self.assertEqual(8993, broker.port)

    def test_parse_url_valid_with_protocol_and_host_name(self):
        broker = Broker.parse("ssl://mybroker")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("mybroker", broker.host_name)
        self.assertEqual(8883, broker.port)

    def test_parse_url_valid_with_protocol_host_name_and_port(self):
        broker = Broker.parse("ssl://mybroker:8993")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("mybroker", broker.host_name)
        self.assertEqual(8993, broker.port)

    def test_parse_url_generates_id(self):
        broker = Broker.parse("mybroker")
        self.assertIsInstance(broker, Broker)
        self.assertIsNotNone(broker.unique_id)
        self.assertIsNot("", broker.unique_id.strip())

    def test_parse_url_valid_with_ipv6_hostname_but_no_port(self):
        broker = Broker.parse("[ff02::1]")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("ff02::1", broker.host_name)
        self.assertEqual(8883, broker.port)

    def test_parse_url_valid_with_ipv6_hostname_and_port(self):
        broker = Broker.parse("[ff02::1]:8993")
        self.assertIsInstance(broker, Broker)
        self.assertEqual("ff02::1", broker.host_name)
        self.assertEqual(8993, broker.port)

    def test_attributes(self):
        self.assertEqual("", self.broker.unique_id)
        self.assertEqual("localhost", self.broker.host_name)
        self.assertIsNone(self.broker.ip_address)
        self.assertEqual(8883, self.broker.port)
        self.assertIsNone(self.broker._response_from_ip_address)
        self.assertIsNone(self.broker._response_time)

    def test_connect_tries_first_using_hostname(self):
        self.broker._parse("broker_guid;8883;broker.fake.com;1.2.3.4")
        self.broker._connect_to_broker()
        self.assertFalse(self.broker._response_from_ip_address)
        self.assertIsNotNone(self.broker._response_time)
        self.connection_mock.assert_called_with(('broker.fake.com', 8883), timeout=ANY)

    def test_connect_uses_ip_address_when_connect_to_hostname_fails(self):
        self.connection_mock.side_effect = [socket.error, self.socket_mock]
        self.broker._parse("broker_guid;8883;broker.fake.com;1.2.3.4")
        self.broker._connect_to_broker()
        self.assertEqual(2, self.connection_mock.call_count)
        self.assertTrue(self.broker._response_from_ip_address)
        self.assertIsNotNone(self.broker._response_time)
        self.connection_mock.assert_called_with(('1.2.3.4', 8883), timeout=ANY)

    def test_close_once(self):
        self.broker._parse("broker_guid;8883;broker.fake.com;1.2.3.4")
        self.broker._connect_to_broker()
        self.assertEqual(1, self.socket_mock.close.call_count)

    def test_close_once_when_errors(self):
        self.connection_mock.side_effect = [socket.error, self.socket_mock]
        self.broker._parse("broker_guid;8883;broker.fake.com;1.2.3.4")
        self.broker._connect_to_broker()
        self.assertEqual(1, self.socket_mock.close.call_count)
