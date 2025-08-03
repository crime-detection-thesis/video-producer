class ConnectionState:
    def __init__(self, camera_id: int, ws):
        self.camera_id = camera_id
        self.ws = ws
        self.pc = None
        self.is_connected = True
        self.user_id = None
