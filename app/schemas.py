from pydantic import BaseModel

class CameraConnectionRequest(BaseModel):
    camera_id: int
    rtsp_url: str

class SDPRequest(BaseModel):
    camera_id: int
    sdp: str
    type: str