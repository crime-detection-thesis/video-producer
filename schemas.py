from pydantic import BaseModel

class CameraConnectionRequest(BaseModel):
    camera_name: str
    rtsp_url: str
