from pydantic import BaseModel

class CameraConnectionRequest(BaseModel):
    camera_name: str
    rtsp_url: str

class SDPRequest(BaseModel):
    camera_name: str
    sdp: str
    type: str