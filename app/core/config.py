from aiortc import RTCConfiguration, RTCIceServer

ice_servers = [
    RTCIceServer(urls="stun:stun.l.google.com:19302"),
    RTCIceServer(
        urls="turn:openrelay.metered.ca:80",
        username="openrelayproject",
        credential="openrelayproject"
    ),
]

config = RTCConfiguration(iceServers=ice_servers)

pcs = set()
