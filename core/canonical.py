"""core/canonical.py — JCS canonicalization and resource hashing."""
import json
import hashlib
from urllib.parse import urlencode, parse_qs


def jcs(obj) -> str:
    """JSON Canonicalization Scheme — sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resource_hash(method: str, path: str, query: str, body: bytes = b"") -> str:
    """
    Compute resource hash:
    sha256: + sha256(f"{METHOD}\n{path}\n{sorted_urlencoded_query}\n{sha256(body).hex()}")
    """
    method_upper = method.upper()

    # Sort query parameters
    if query:
        parsed = parse_qs(query, keep_blank_values=True)
        # Sort by key, then rejoin
        sorted_params = sorted(
            [(k, v) for k, vs in parsed.items() for v in vs],
            key=lambda x: x[0]
        )
        sorted_query = urlencode(sorted_params)
    else:
        sorted_query = ""

    body_hash = hashlib.sha256(body).hexdigest()
    content = f"{method_upper}\n{path}\n{sorted_query}\n{body_hash}"
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{h}"
