"""A Python module for iteracting with Slack's Web API."""

# Standard Imports
import asyncio
from typing import Optional, Union

# ThirdParty Imports
import aiohttp
from aiohttp import FormData

# Internal Imports
from slack.web.base_client import BaseClient, SlackResponse
import slack.errors as err


class WebClient(BaseClient):
    """A WebClient allows apps to communicate with the Slack Platform's Web API.

    The Slack Web API is an interface for querying information from
    and enacting change in a Slack workspace.

    This client handles constructing and sending HTTP requests to Slack
    as well as parsing any responses received into a `SlackResponse`.

    Attributes:
        token (str): A string specifying an xoxp or xoxb token.
        use_session (bool): An boolean specifying if the client
            should take advantage of connection pooling.
            Default is True.
        base_url (str): A string representing the Slack API base URL.
            Default is 'https://www.slack.com/api/'
        timeout (int): The maximum number of seconds the client will wait
            to connect and receive a response from Slack.
            Default is 30 seconds.

    Methods:
        api_call: Constructs a request and executes the API call to Slack.

    Example of recommended usage:
    ```python
        import os
        import slack

        client = slack.WebClient(token=os.environ['SLACK_API_TOKEN'])
        response = client.chat_postMessage(
            channel='#random',
            text="Hello world!")
        assert response["ok"]
        assert response["message"]["text"] == "Hello world!"
    ```

    Example manually creating an API request:
    ```python
        import os
        import slack

        client = slack.WebClient(token=os.environ['SLACK_API_TOKEN'])
        response = client.api_call(
            api_method='chat.postMessage',
            json={'channel': '#random','text': "Hello world!"}
        )
        assert response["ok"]
        assert response["message"]["text"] == "Hello world!"
    ```

    Note:
        Any attributes or methods prefixed with _underscores are
        intended to be "private" internal use only. They may be changed or
        removed at anytime.
    """

    def __init__(
        self, loop: Optional[asyncio.AbstractEventLoop] = None, *args, **kwargs
    ):
        super(WebClient, self).__init__(*args, **kwargs)
        self._event_loop = loop

    def api_call(
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: dict = None,
        data: Union[dict, FormData] = None,
        params: dict = None,
        json: dict = None,
    ) -> asyncio.Future:
        """Create a request and execute the API call to Slack.

        Args:
            api_method (str): The target Slack API method.
                e.g. 'chat.postMessage'
            http_verb (str): HTTP Verb. e.g. 'POST'
            files (dict): Files to multipart upload.
                e.g. {imageORfile: file_objectORfile_path}
            data: The body to attach to the request. If a dictionary is
                provided, form-encoding will take place.
                e.g. {'key1': 'value1', 'key2': 'value2'}
            params (dict): The URL parameters to append to the URL.
                e.g. {'key1': 'value1', 'key2': 'value2'}
            json (dict): JSON for the body to attach to the request
                (if files or data is not specified).
                e.g. {'key1': 'value1', 'key2': 'value2'}

        Returns:
            (SlackResponse)
                The server's response to an HTTP request. Data
                from the response can be accessed like a dict.
                If the response included 'next_cursor' it can
                be iterated on to execute subsequent requests.

        Raises:
            SlackApiError: The following Slack API call failed:
                'chat.postMessage'.
            SlackRequestError: Json data can only be submitted as
                POST requests.
        """
        has_json = json is not None
        has_files = files is not None
        if has_json and http_verb != "POST":
            msg = "Json data can only be submitted as POST requests. GET requests should use the 'params' argument."
            raise err.SlackRequestError(msg)

        api_url = self._get_url(api_method)

        req_args = {
            "headers": self._get_headers(has_json, has_files),
            "data": data,
            "files": files,
            "params": params,
            "json": json,
            "ssl": self.ssl,
            "proxy": self.proxy,
        }

        if self._event_loop is None:
            self._event_loop = self._get_event_loop()

        future = asyncio.ensure_future(
            self._send(http_verb=http_verb, api_url=api_url, req_args=req_args),
            loop=self._event_loop,
        )

        return future

    def _get_event_loop(self):
        """Retrieves the event loop or creates a new one."""
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    async def _send(self, http_verb, api_url, req_args):
        """Sends the request out for transmission.

        Args:
            http_verb (str): The HTTP verb. e.g. 'GET' or 'POST'.
            api_url (str): The Slack API url. e.g. 'https://slack.com/api/chat.postMessage'
            req_args (dict): The request arguments to be attached to the request.
            e.g.
            {
                json: {
                    'attachments': [{"pretext": "pre-hello", "text": "text-world"}],
                    'channel': '#random'
                }
            }
        Returns:
            The response parsed into a SlackResponse object.
        """
        open_files = []
        files = req_args.pop("files", None)
        if files is not None:
            for k, v in files.items():
                if isinstance(v, str):
                    f = open(v.encode("ascii", "ignore"), "rb")
                    open_files.append(f)
                    req_args["data"].update({k: f})
                else:
                    req_args["data"].update({k: v})

        res = await self._request(
            http_verb=http_verb, api_url=api_url, req_args=req_args
        )

        for f in open_files:
            f.close()

        data = {
            "client": self,
            "http_verb": http_verb,
            "api_url": api_url,
            "req_args": req_args,
        }
        return SlackResponse(**{**data, **res}).validate()

    async def _request(self, *, http_verb, api_url, req_args):
        """Submit the HTTP request with the running session or a new session.
        Returns:
            A dictionary of the response data.
        """
        if self.session and not self.session.closed:
            async with self.session.request(http_verb, api_url, **req_args) as res:
                return {
                    "data": await res.json(),
                    "headers": res.headers,
                    "status_code": res.status,
                }
        async with aiohttp.ClientSession(
            loop=self._event_loop, timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            async with session.request(http_verb, api_url, **req_args) as res:
                return {
                    "data": await res.json(),
                    "headers": res.headers,
                    "status_code": res.status,
                }
