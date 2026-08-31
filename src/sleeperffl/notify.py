"""Push notifications via ntfy."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class Notifier:
    server: str
    topic: str
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
        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        }
        if click:
            headers["Click"] = click
        try:
            response = httpx.post(
                f"{self.server.rstrip('/')}/{self.topic}",
                content=message.encode("utf-8"),
                headers=headers,
                timeout=15.0,
            )
            return response.status_code < 300
        except httpx.HTTPError:
            return False
