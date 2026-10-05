from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_key(request: Request) -> str:
    """Stable client identity behind the proxy chain.

    In production the request arrives through Cloudflare -> Render's
    proxy, so request.client.host is an edge IP that rotates on every
    request: each call would look like a brand-new visitor and the
    counter would never reach its limit (verified: 36 logins, zero
    429s). Cloudflare writes the visitor's real IP into
    CF-Connecting-IP and overwrites it on every incoming request, so a
    client cannot spoof it. Without the header (local development,
    tests) fall back to the socket address.
    """
    visitor_ip = request.headers.get("cf-connecting-ip")
    if visitor_ip:
        return visitor_ip.strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_key)
