import socket
import json


class TCPRemote:
    def __init__(self, config):
        self.cfg = config
        self.host = self.cfg['acq']['tcp_host']
        self.port = int(self.cfg['acq']['tcp_port'])
        
    def save_to_cfg(self):
        self.cfg['acq']['tcp_host'] = self.host
        self.cfg['acq']['tcp_port'] = str(self.port)
        
    def send(self, msg):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            s.sendall(json.dumps(msg).encode('utf-8'))
            # response = json.loads((s.recv(1024)))
            response_data = b""
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break  # connection closed by server
                response_data += chunk
                # Check if we've reached the end of the message (if newline is the delimiter)
                if b'\n' in chunk:  
                    break  # Stop reading when a newline is found
            response = json.loads(response_data)
            return response
        