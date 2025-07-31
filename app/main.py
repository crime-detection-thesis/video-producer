from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes.camera import router as camera_router
from .routes.frame_receiver import router as frame_receiver_router
from .routes.health import router as health_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(camera_router, prefix="/camera")
app.include_router(frame_receiver_router, prefix="/frames")
app.include_router(health_router, prefix="/health")
