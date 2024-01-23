import socket
import json
import utils


class RemoteControlTCP:
    def __init__(self, host, port, command_trigger, response_queue):
        self.host = host
        self.port = port
        self.command_trigger = command_trigger
        self.response_queue = response_queue
        self.is_running = False

    def run(self):
        self.is_running = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, self.port))
            s.listen()
            s.settimeout(1.0)
            utils.log_info("RemoteTCP", f"Listening on {self.host} port {self.port}...")

            while self.is_running:
                try:
                    conn, addr = s.accept()
                    with conn:
                        utils.log_info("RemoteTCP", f"Connected by {addr}")
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
                                self.command_trigger.transmit(request['msg'], *request.get('args', []), **request.get('kwargs', {}))
                                
                                # Block until the main process processes the data and sends back the result
                                response = self.response_queue.get()
                                conn.sendall(json.dumps(response).encode('utf-8'))
                                
                            except json.decoder.JSONDecodeError:
                                utils.log_error("RemoteTCP", "JSON decode error.")
                                
                except socket.timeout:
                    # Check the flag periodically
                    if not self.is_running:
                        utils.log_info("RemoteTCP", "Connection closed.")
                        
                        # Alert the main thread that the connection is closed
                        self.command_trigger.transmit("STOP SERVER")
                        break
    
    def close(self):
        self.is_running = False

