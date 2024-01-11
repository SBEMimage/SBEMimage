import socket
import json
import utils


class RemoteControlTCP:
    def __init__(self, host, port, main_controls_trigger):
        self.host = host
        self.port = port
        self.main_controls_trigger = main_controls_trigger
        self.server_socket = None

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as self.server_socket:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()
            utils.log_info("RemoteTCP", f"Listening on {self.host} port {self.port}...")

            while True:
                try:
                    conn, addr = self.server_socket.accept()
                    with conn:
                        print(f"Connected by {addr}")
                        data = conn.recv(1024)
                        if data:
                            try:
                                request = json.loads(data)
                                msg = request.get('msg')
                                args = request.get('args', [])
                                kwargs = request.get('kwargs', {})
                                
                                # Check if request is valid
                                if 'msg' not in request or not isinstance(msg, str) or not isinstance(args, list) or not isinstance(kwargs, dict):
                                    utils.log_error("RemoteTCP", "Invalid request.")
                                    continue
                                
                                # Transmit request to main controls
                                self.main_controls_trigger.transmit(request['msg'], *request.get('args', []), **request.get('kwargs', {}))
                                
                            except json.decoder.JSONDecodeError:
                                utils.log_error("RemoteTCP", "JSON decode error.")
                                
                except ConnectionAbortedError:
                    utils.log_info("RemoteTCP", "Connection aborted.")
                    return
    
    def close(self):
        if self.server_socket:
            self.server_socket.close()
