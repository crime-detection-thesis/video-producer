import asyncio, json, httpx
from datetime import datetime
from app.utils.hmac import make_hmac_headers
from app.constants import UPLOAD_URL, INCIDENT_WINDOW

buffer_store: dict[tuple[str, str], list[dict]] = {}
incident_tasks: dict[tuple[str, str], asyncio.Task] = {}

async def buffer_frame(camera_id: str, user_id: str, frame_bytes: bytes, detections: list, confidence: float):
    entry = {
        "frame": frame_bytes,
        "detections": detections,
        "confidence": confidence,
        "timestamp": datetime.utcnow().isoformat()
    }
    key = (camera_id, user_id)
    buf = buffer_store.setdefault(key, [])
    buf.append(entry)

    if key not in incident_tasks:
        print(f"[{key}] Iniciando tarea de flush.")
        incident_tasks[key] = asyncio.create_task(flush_after_window(key))

async def flush_after_window(key: tuple[str, str]):
    await asyncio.sleep(INCIDENT_WINDOW)
    frames = buffer_store.pop(key, [])
    incident_tasks.pop(key, None)
    if not frames:
        return

    first, last = frames[0], frames[-1]
    best = max(frames, key=lambda e: e["confidence"])
    selected = [first, best, last]
    timestamps = [e["timestamp"] for e in selected]
    files = {f"frame_{i}": e["frame"] for i, e in enumerate(selected)}
    detections = [e["detections"] for e in selected]

    payload = {
        "camera_id": str(key[0]),
        "user_id":   str(key[1]),
        "timestamps": json.dumps(timestamps)
    }
    headers = make_hmac_headers(payload)
    payload['detections'] = json.dumps(detections)

    async with httpx.AsyncClient() as client:
        await client.post(
            UPLOAD_URL,
            data=payload,
            files=files,
            headers=headers,
            timeout=30.0
        )
    print(f"[{key}] Incidente registrado con {len(selected)} imágenes.")
