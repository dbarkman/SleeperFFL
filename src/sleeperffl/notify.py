"""Push notifications via ntfy.

Points at a self-hosted ntfy instance by default. The token authenticates the
publish; without it a private server (``auth-default-access: deny-all``) returns
403.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

MAX_ATTEMPTS = 4
BACKOFF_BASE = 1.0
BACKOFF_CAP = 20.0

# A daily-quota 429 will not clear by retrying, so it is reported rather than
# hammered. Everything else transient gets backed off and retried.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass
class Notifier:
    server: str
    topic: str
    token: str | None = None
    enabled: bool = True

    def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "football",
        click: str | None = None,
    ) -> bool:
        """Post one notification. Returns False if it could not be delivered."""
        if not self.enabled:
            return False

        headers = {"Title": title, "Priority": priority, "Tags": tags}
        if click:
            headers["Click"] = click
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        url = f"{self.server.rstrip('/')}/{self.topic}"
        body = message.encode("utf-8")

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = httpx.post(url, content=body, headers=headers, timeout=15.0)
            except httpx.HTTPError:
                pass
            else:
                if response.status_code < 300:
                    return True
                if response.status_code not in RETRY_STATUS:
                    return False
                # A quota 429 is not worth retrying; a throttle 429 is.
                if response.status_code == 429 and b"quota" in response.content.lower():
                    return False

            if attempt < MAX_ATTEMPTS - 1:
                delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
                time.sleep(delay + random.uniform(0, delay * 0.1))

        return False
