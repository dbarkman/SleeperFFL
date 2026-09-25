"""Push notifications via ntfy.

Points at a self-hosted ntfy instance by default. The token authenticates the
publish; without it a private server (``auth-default-access: deny-all``) returns
403.

Messages are published as a single JSON document to the server root rather
than as a POST to the topic with ``Title``/``Tags`` headers. HTTP headers are
ASCII-only, so a title containing an em dash or a player name with an accent
would fail to encode; a JSON body carries any UTF-8 text.
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

# ntfy's JSON API takes priority as 1-5 rather than the header names.
PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}


@dataclass
class Notifier:
    server: str
    topic: str
    token: str | None = None
    enabled: bool = True

    def payload(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "football",
        click: str | None = None,
    ) -> dict:
        body = {
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": PRIORITY.get(priority, 3),
            "tags": [tag.strip() for tag in tags.split(",") if tag.strip()],
        }
        if click:
            body["click"] = click
        return body

    def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "football",
        click: str | None = None,
    ) -> bool:
        """Post one notification. Returns False if it could not be delivered.

        Never raises: a single undeliverable alert must not abort the rest of a
        watcher run.
        """
        if not self.enabled:
            return False

        try:
            body = self.payload(title, message, priority, tags, click)
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            url = self.server.rstrip("/") + "/"

            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = httpx.post(url, json=body, headers=headers, timeout=15.0)
                except httpx.HTTPError:
                    pass
                else:
                    if response.status_code < 300:
                        return True
                    if response.status_code not in RETRY_STATUS:
                        return False
                    if response.status_code == 429 and b"quota" in response.content.lower():
                        return False

                if attempt < MAX_ATTEMPTS - 1:
                    delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
                    time.sleep(delay + random.uniform(0, delay * 0.1))
        except Exception:
            return False

        return False
