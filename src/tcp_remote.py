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
            response = json.loads((s.recv(1024)))
            return response
        