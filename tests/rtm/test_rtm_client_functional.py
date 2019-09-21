# Standard Imports
import collections
import unittest
from unittest import mock

# ThirdParty Imports
import asyncio
from aiohttp import web, WSCloseCode
import json

# Internal Imports
import slack
import slack.errors as e
from tests.helpers import async_test, fake_send_req_args, mock_rtm_response


@mock.patch("slack.WebClient._send", new_callable=mock_rtm_response)
class TestRTMClientFunctional(unittest.TestCase):
    async def echo(self, ws, path):
        async for message in ws:
            await ws.send(
                json.dumps({"type": "message", "message_sent": json.loads(message)})
            )

    async def mock_server(self):
        app = web.Application()
        app["websockets"] = []
        app.router.add_get("/", self.websocket_handler)
        app.on_shutdown.append(self.on_shutdown)
        runner = web.AppRunner(app)
        await runner.setup()
        self.site = web.TCPSite(runner, "localhost", 8765)
        await self.site.start()

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        request.app["websockets"].append(ws)
        try:
            async for msg in ws:
                await ws.send_json({"type": "message", "message_sent": msg.json()})
        finally:
            request.app["websockets"].remove(ws)
        return ws

    async def on_shutdown(self, app):
        for ws in set(app["websockets"]):
            await ws.close(code=WSCloseCode.GOING_AWAY, message="Server shutdown")

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        task = asyncio.ensure_future(self.mock_server(), loop=self.loop)
        self.loop.run_until_complete(asyncio.wait_for(task, 0.1))
        self.client = slack.RTMClient(
            token="xoxa-1234", loop=self.loop, auto_reconnect=False
        )

    def tearDown(self):
        self.loop.run_until_complete(self.site.stop())
        slack.RTMClient._callbacks = collections.defaultdict(list)

    @async_test
    async def test_client_auto_reconnects_if_connection_randomly_closes(
        self, mock_rtm_response
    ):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            rtm_client = payload["rtm_client"]

            if rtm_client._connection_attempts == 1:
                await rtm_client._close_websocket()
            else:
                self.assertEqual(rtm_client._connection_attempts, 2)
                await rtm_client.stop()

        client = slack.RTMClient(token="xoxa-1234", auto_reconnect=True)
        await client.start()

    @async_test
    async def test_client_auto_reconnects_if_an_error_is_thrown(
        self, mock_rtm_response
    ):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            rtm_client = payload["rtm_client"]

            if rtm_client._connection_attempts == 1:
                raise e.SlackApiError("Test Error", {"headers": {"Retry-After": 0.001}})
            else:
                self.assertEqual(rtm_client._connection_attempts, 2)
                await rtm_client.stop()

        client = slack.RTMClient(token="xoxa-1234", auto_reconnect=True)
        await client.start()

    @async_test
    async def test_open_event_receives_expected_arguments(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            self.assertIsInstance(payload["data"], dict)
            self.assertIsInstance(payload["web_client"], slack.WebClient)
            rtm_client = payload["rtm_client"]
            self.assertIsInstance(rtm_client, slack.RTMClient)
            await rtm_client.stop()

        await self.client.start()

    @async_test
    async def test_stop_closes_websocket(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            self.assertFalse(self.client._websocket.closed)

            rtm_client = payload["rtm_client"]
            await rtm_client.stop()

        await self.client.start()
        self.assertIsNone(self.client._websocket)

    @async_test
    async def test_start_calls_rtm_connect_by_default(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            self.assertFalse(self.client._websocket.closed)
            rtm_client = payload["rtm_client"]
            await rtm_client.stop()

        await self.client.start()
        mock_rtm_response.assert_called_once_with(
            http_verb="GET",
            api_url="https://www.slack.com/api/rtm.connect",
            req_args=fake_send_req_args(),
        )

    @async_test
    async def test_start_calls_rtm_start_when_specified(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            self.assertFalse(self.client._websocket.closed)
            rtm_client = payload["rtm_client"]
            await rtm_client.stop()

        self.client.connect_method = "rtm.start"
        await self.client.start()
        mock_rtm_response.assert_called_once_with(
            http_verb="GET",
            api_url="https://www.slack.com/api/rtm.start",
            req_args=fake_send_req_args(),
        )

    @async_test
    async def test_send_over_websocket_sends_expected_message(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def echo_message(**payload):
            rtm_client = payload["rtm_client"]
            message = {
                "id": 1,
                "type": "message",
                "channel": "C024BE91L",
                "text": "Hello world",
            }
            await rtm_client.send_over_websocket(payload=message)

        @slack.RTMClient.run_on(event="message")
        async def check_message(**payload):
            message = {
                "id": 1,
                "type": "message",
                "channel": "C024BE91L",
                "text": "Hello world",
            }
            rtm_client = payload["rtm_client"]
            self.assertDictEqual(payload["data"]["message_sent"], message)
            await rtm_client.stop()

        await self.client.start()

    @async_test
    async def test_ping_sends_expected_message(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def ping_message(**payload):
            rtm_client = payload["rtm_client"]
            await rtm_client.ping()

        @slack.RTMClient.run_on(event="message")
        async def check_message(**payload):
            message = {"id": 1, "type": "ping"}
            rtm_client = payload["rtm_client"]
            self.assertDictEqual(payload["data"]["message_sent"], message)
            await rtm_client.stop()

        await self.client.start()

    @async_test
    async def test_typing_sends_expected_message(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def typing_message(**payload):
            rtm_client = payload["rtm_client"]
            await rtm_client.typing(channel="C01234567")

        @slack.RTMClient.run_on(event="message")
        async def check_message(**payload):
            message = {"id": 1, "type": "typing", "channel": "C01234567"}
            rtm_client = payload["rtm_client"]
            self.assertDictEqual(payload["data"]["message_sent"], message)
            await rtm_client.stop()

        await self.client.start()

    @async_test
    async def test_on_error_callbacks(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        def raise_an_error(**payload):
            raise e.SlackClientNotConnectedError("Testing error handling.")

        @slack.RTMClient.run_on(event="error")
        def error_callback(**payload):
            self.error_hanlding_mock(str(payload["data"]))

        self.error_hanlding_mock = mock.Mock()
        with self.assertRaises(e.SlackClientNotConnectedError):
            await self.client.start()
        self.error_hanlding_mock.assert_called_once()

    @async_test
    async def test_callback_errors_are_raised(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        def raise_an_error(**payload):
            raise Exception("Testing error handling.")

        with self.assertRaises(Exception) as context:
            await self.client.start()

        expected_error = "Testing error handling."
        self.assertIn(expected_error, str(context.exception))

    @async_test
    async def test_on_close_callbacks(self, mock_rtm_response):
        @slack.RTMClient.run_on(event="open")
        async def stop_on_open(**payload):
            await payload["rtm_client"].stop()

        @slack.RTMClient.run_on(event="close")
        def assert_on_close(**payload):
            self.close_mock(str(payload["data"]))

        self.close_mock = mock.Mock()
        await self.client.start()
        self.close_mock.assert_called_once()
