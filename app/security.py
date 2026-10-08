from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def safe_url(value):
    if not value or not isinstance(value, str) or len(value) > 4000:
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
            return None
        if any(ord(c) < 32 for c in value):
            return None
        return value
    except ValueError:
        return None

def canonical_url(value):
    value = safe_url(value)
    if not value:
        return None
    url = urlsplit(value)
    # Remove only known tracking fields; retain parameters that may identify the job.
    query = [(k, v) for k, v in parse_qsl(url.query) if not k.lower().startswith("utm_")]
    return urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path.rstrip("/"), urlencode(query), ""))
