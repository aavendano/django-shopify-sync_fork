import json
import time
from urllib import error, request

from .models.session import API_VERSION


class ShopifyGraphQLError(Exception):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or []


class ShopifyGraphQLClient:
    def __init__(
        self,
        session,
        *,
        api_version=API_VERSION,
        timeout=30,
        min_available=50,
        throttle=True,
    ):
        self.session = session
        self.api_version = api_version
        self.timeout = timeout
        self.min_available = min_available
        self.throttle = throttle

    def execute(self, query, variables=None):
        payload = json.dumps(
            {
                "query": query,
                "variables": variables or {},
            }
        ).encode("utf-8")
        url = self._endpoint()
        req = request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.session.token,
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise ShopifyGraphQLError(
                f"Shopify GraphQL request failed: {exc.reason}"
            ) from exc

        data = json.loads(body)
        errors = data.get("errors") or []
        if errors:
            raise ShopifyGraphQLError("Shopify GraphQL error response.", errors=errors)

        extensions = data.get("extensions") or {}
        if self.throttle:
            self._apply_throttle(extensions)

        return data.get("data"), extensions

    def _endpoint(self):
        site = self.session.site
        if site.startswith("http://") or site.startswith("https://"):
            base = site
        else:
            base = f"https://{site}"
        return f"{base}/admin/api/{self.api_version}/graphql.json"

    def _apply_throttle(self, extensions):
        cost = extensions.get("cost") or {}
        throttle_status = cost.get("throttleStatus") or {}
        available = throttle_status.get("currentlyAvailable")
        restore_rate = throttle_status.get("restoreRate")
        if (
            available is None
            or restore_rate in (None, 0)
            or available >= self.min_available
        ):
            return
        wait_seconds = (self.min_available - available) / restore_rate
        if wait_seconds <= 0:
            return
        time.sleep(wait_seconds)
