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
    
    def get_commands(self, kwargs):
        return self.send('GET COMMANDS', **kwargs)
    
    def test_connection(self):
        return self.send('TEST CONNECTION')
        
    def send(self, msg, *args, **kwargs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))

            command = {'msg': msg, 'args': args, 'kwargs': kwargs}

            s.sendall(json.dumps(command).encode('utf-8'))
            response = json.loads((s.recv(1024)))
            return response