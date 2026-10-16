"""HTTP clients for calls GVC makes to its siblings (GAM, Notes).

One place builds them, so tests can swap the transport for an `httpx.MockTransport`
and fake both siblings without a network, the way GAM fakes fal.ai.
"""

from typing import Dict, Optional

import httpx

# Tests set this; production leaves it None, which is httpx's real network transport.
TRANSPORT: Optional[httpx.BaseTransport] = None


def client(base_url: str, *, timeout: float, headers: Optional[Dict[str, str]] = None) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers or {},
        transport=TRANSPORT,
        # Never follow a redirect to somewhere else: the base URLs are configured, and a
        # sibling that answers with a redirect is misconfigured, not something to chase.
        follow_redirects=False,
    )
