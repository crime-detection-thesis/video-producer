from typing import Dict, Any
from fastapi import WebSocket

camera_buffers: Dict[int, Any] = {}
camera_viewers: Dict[int, int] = {}
camera_user_map: Dict[int, str] = {}
signaling_websockets: Dict[int, WebSocket] = {}
