""" Tests various methods of the DxlClient """

from __future__ import absolute_import
from __future__ import print_function
import threading
import time

from nose.plugins.attrib import attr
from dxlclient import UuidGenerator, ServiceRegistrationInfo, Request, ErrorResponse, EventCallback, Event
from dxlclient.test.base_test import BaseClientTest
from dxlclient.test.test_service import TestService

# pylint: disable=missing-docstring


@attr('system')
class DxlClientTest(BaseClientTest):

    #
    # Tests the connect and disconnect methods of the DxlClient
    #
    @attr('system')
    def test_connect_and_disconnect(self):
        with self.create_client(max_retries=0) as client:
            client.connect()
            self.assertTrue(client.connected)
            client.disconnect()
            self.assertFalse(client.connected)

    #
    # Tests the subscribe and unsubscribe methods of the DxlClient
    #
    @attr('system')
    def test_subscribe_and_unsubscribe(self):
        with self.create_client(max_retries=0) as client:
            client.connect()
            topic = UuidGenerator.generate_id_as_string()
            client.subscribe(topic)
            self.assertIn(topic, client.subscriptions)
            client.unsubscribe(topic)
            self.assertNotIn(topic, client.subscriptions)

    #
    # Tests that an unsubscribe call made after a previous unsubscribe for the
    # same topic does not raise an error.
    #
    @attr('system')
    def test_unsubscribe_for_unknown_topic_does_not_raise_error(self):
        with self.create_client(max_retries=0) as client:
            client.connect()
            topic = UuidGenerator.generate_id_as_string()
            client.subscribe(topic)
            self.assertIn(topic, client.subscriptions)
            client.unsubscribe(topic)
            client.unsubscribe(topic)
            self.assertNotIn(topic, client.subscriptions)

    #
    # Test to ensure that ErrorResponse messages can be successfully delivered
    # from a service to a client.
    #
    @attr('system')
    def test_error_message(self):
        with self.create_client() as client:
            test_service = TestService(client, 1)
            client.connect()

            error_code = 9090
            error_message = "My error message"

            topic = UuidGenerator.generate_id_as_string()

            #
            # Create a test service that returns error messages
            #

            reg_info = ServiceRegistrationInfo(client, "testErrorMessageService")
            reg_info.add_topic(topic, test_service)
            client.register_service_sync(reg_info, self.DEFAULT_TIMEOUT)

            test_service.return_error = True
            test_service.error_code = error_code
            test_service.error_message = error_message
            client.add_request_callback(topic, test_service)

            # Send a request and ensure the response is an error message
            response = client.sync_request(Request(topic))
            self.assertIsInstance(response, ErrorResponse, msg="Response is not an ErrorResponse")
            self.assertEqual(error_code, response.error_code)
            self.assertEqual(error_message, response.error_message)

    #
    # Tests threading of incoming requests
    #
    @attr('system')
    def test_incoming_message_threading(self):
        max_wait = 30
        thread_count = 10
        thread_name_condition = threading.Condition()
        thread_name = set()

        event_topic = UuidGenerator.generate_id_as_string()
        with self.create_client(incoming_message_thread_pool_size=
                                thread_count) as client:
            client.connect()
            event_callback = EventCallback()

            def on_event(_):
                with thread_name_condition:
                    thread_name.add(threading.current_thread())
                    if len(thread_name) == thread_count:
                        thread_name_condition.notify_all()

            event_callback.on_event = on_event
            client.add_event_callback(event_topic, event_callback)

            for _ in range(0, 1000):
                evt = Event(event_topic)
                client.send_event(evt)

            start = time.time()
            with thread_name_condition:
                while (time.time() - start < max_wait) and \
                        len(thread_name) < thread_count:
                    thread_name_condition.wait(max_wait)

            self.assertEqual(thread_count, len(thread_name))
