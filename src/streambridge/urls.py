"""URL rules: allowed schemes, credential handling and masking, TLS policy.

Credentials are never logged. Use mask() for anything shown to the user or logs.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https", "rtsp", "rtsps", "rtmp", "rtmps", "hls")
# "hls" is accepted as a user-friendly alias: hls://host/x.m3u8 -> https://host/x.m3u8


class UrlError(ValueError):
    """Raised for URLs StreamBridge refuses to open."""


@dataclass(frozen=True)
class StreamUrl:
    url: str            # URL handed to FFmpeg (may contain credentials)
    display: str        # masked, safe to show and log
    host: str
    scheme: str
    is_private: bool    # LAN / loopback / link-local host

    def __repr__(self) -> str:  # never leak credentials through repr()
        return f"StreamUrl({self.display!r})"

    __str__ = __repr__


_CRED_RE = re.compile(r"(?P<pre>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]*@")


def mask(text: str) -> str:
    """Replace user:password@ in any URL found in text with ***@."""
    if not text:
        return text
    return _CRED_RE.sub(lambda m: m.group("pre") + "***@", text)


def is_private_host(host: str) -> bool:
    h = host.strip("[]").lower()
    if h in ("localhost",) or h.endswith(".local") or h.endswith(".lan") or h.endswith(".home.arpa"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def normalize(value: str) -> str:
    """Trim; add http:// when the user typed just 'ip:port/path' (as EZ-Cam shows it)."""
    value = (value or "").strip()
    if value and "://" not in value and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)", value):
        value = "http://" + value
    return value


def split_credentials(url: str) -> tuple[str, str, str]:
    """'https://u:p@h/x' -> ('https://h/x', 'u', 'p'). Used to move login-in-URL into the fields."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url, "", ""
    userinfo, _, hostport = parts.netloc.rpartition("@")
    user, _, pwd = userinfo.partition(":")
    return urlunsplit((parts.scheme, hostport, parts.path, parts.query, parts.fragment)), unquote(user), unquote(pwd)


def guess_audio_url(video_url: str) -> str:
    """'Same phone': http://ip:port/video -> http://ip:port/audio.wav (EZ-Cam layout)."""
    parts = urlsplit(normalize(video_url))
    if not parts.scheme or not parts.hostname:
        return ""
    return split_credentials(urlunsplit((parts.scheme, parts.netloc, "/audio.wav", "", "")))[0]


def add_recent(recent: list[str], url: str, limit: int = 8) -> list[str]:
    url = split_credentials(url)[0]  # never store credentials in the list
    return ([url] + [u for u in recent if u != url])[:limit] if url else list(recent)


def _checked_parts(raw: str):
    """Syntax checks shared by parse(): returns (urlsplit parts, scheme, host, port) or raises UrlError."""
    raw = (raw or "").strip()
    if not raw:
        raise UrlError("URL is empty")
    if any(c in raw for c in "\r\n\t ") or any(ord(c) < 32 for c in raw):
        raise UrlError("URL contains spaces or control characters")
    parts = urlsplit(normalize(raw))
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlError(f"'{scheme}' URLs are not allowed; use one of: "
                       + ", ".join(s for s in ALLOWED_SCHEMES if s != "rtsps" and s != "rtmps"))
    host = parts.hostname or ""
    if not host:
        raise UrlError("URL has no host")
    try:
        port = parts.port
    except ValueError as e:
        raise UrlError("URL has an invalid port") from e
    if port == 0:
        raise UrlError("URL has an invalid port")
    return parts, scheme, host, port


def _credentials(user: str, pwd: str) -> str:
    """'user:pass@' (percent-encoded), 'user@', or '' when there is no login."""
    if not (user or pwd):
        return ""
    return quote(user, safe="") + (":" + quote(pwd, safe="") if pwd else "") + "@"


def parse(raw: str, username: str = "", password: str = "") -> StreamUrl:
    """Validate a user-supplied URL and merge optional login fields into it."""
    parts, scheme, host, port = _checked_parts(raw)
    cred = _credentials(username or unquote(parts.username or ""), password or unquote(parts.password or ""))
    if scheme == "hls":
        scheme = "https"
    netloc_host = f"[{host}]" if ":" in host else host
    if port:
        netloc_host += f":{port}"
    url = urlunsplit((scheme, cred + netloc_host, parts.path or "/", parts.query, ""))
    display = urlunsplit((scheme, ("***@" if cred else "") + netloc_host, parts.path or "/", parts.query, ""))
    return StreamUrl(url=url, display=display, host=host, scheme=scheme, is_private=is_private_host(host))


def ffmpeg_options(u: StreamUrl, strict_tls: bool = False, timeout_s: float = 8.0) -> dict[str, str]:
    """FFmpeg/PyAV options for opening u.

    TLS: certificates are verified for public hosts. Self-signed certificates
    (EZ-Cam's LAN HTTPS) are accepted only for private/LAN hosts, unless strict.
    """
    us = str(int(timeout_s * 1_000_000))
    opts: dict[str, str] = {}
    if u.scheme in ("http", "https", "hls"):
        opts.update({"rw_timeout": us, "reconnect": "0", "user_agent": "StreamBridge"})
    if u.scheme.startswith("rtsp"):
        opts.update({"timeout": us, "rtsp_transport": "tcp"})
    if u.scheme.startswith("rtmp"):
        opts.update({"rw_timeout": us})
    if u.scheme in ("https", "rtsps", "rtmps"):
        verify = strict_tls or not u.is_private
        opts["tls_verify"] = "1" if verify else "0"
        if verify:
            try:
                import certifi  # optional, helps on Windows/macOS frozen builds
                opts["ca_file"] = certifi.where()
            except ImportError:
                pass
    # Low latency: phone streams are live; don't buffer seconds of data while probing.
    opts.update({"probesize": "8192", "analyzeduration": "500000", "fflags": "nobuffer"})
    # Restrict FFmpeg to network protocols (no file:, pipe:, concat: tricks from playlists).
    opts["protocol_whitelist"] = "http,https,tcp,tls,udp,rtp,rtsp,rtsps,rtmp,rtmps,crypto,httpproxy"
    return opts
