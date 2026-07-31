# core/tally_client.py

import time
import requests
from requests.adapters import HTTPAdapter, Retry
import logging

logger = logging.getLogger(__name__)

class TallyClient:
    """Handles HTTP/XML requests to Tally."""
    def __init__(self, host: str, port: int, timeout: int = 300):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        # Only retry on HTTP 5xx errors — NOT on timeouts.
        # Retrying a timeout hammers Tally with the same large query again.
        retry = Retry(
            total=2,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        return session

    def send_request(self, xml_payload: str) -> str:
        """Send XML payload to Tally and return response string."""
        # 1-second delay between requests so Tally can breathe
        time.sleep(1.0)
        headers = {"Content-Type": "application/xml; charset=utf-8"}
        resp = self.session.post(
            self.base_url,
            data=xml_payload.encode("utf-8"),
            headers=headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.text
