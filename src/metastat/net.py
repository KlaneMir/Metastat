"""HTTPS client that uses the Windows certificate store.

By default httpx trusts only its own certificate list (certifi). On computers with an antivirus or a network
filter that signs connections with its own certificate from the Windows store, this ends with a
CERTIFICATE_VERIFY_FAILED error. truststore makes it trust what the system trusts (like the browser and pip);
certificate verification stays on.
"""
from __future__ import annotations

import ssl

import httpx


def ssl_context() -> ssl.SSLContext | bool:
    try:
        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def client(**kw) -> httpx.Client:
    kw.setdefault("verify", ssl_context())
    kw.setdefault("timeout", 60)
    return httpx.Client(**kw)
