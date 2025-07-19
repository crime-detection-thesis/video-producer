import time
import json
import hmac
import hashlib
from app.constants import UPLOAD_SECRET

def make_hmac_headers(payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sig = hmac.new(UPLOAD_SECRET, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    
    return {
        "X-Timestamp": ts,
        "X-Signature": sig
    }
