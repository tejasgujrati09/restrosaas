from __future__ import annotations

import secrets

import segno

from app.config import settings


def new_qr_token() -> str:
    """12 URL-safe characters (72 bits): short enough for a small printed QR."""
    return secrets.token_urlsafe(9)


def qr_url(token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/t/{token}"


def qr_svg(token: str) -> str:
    return segno.make(qr_url(token), error="m").svg_inline(scale=4, border=1)
