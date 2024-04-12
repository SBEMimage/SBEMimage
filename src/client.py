import socket
import json

# host = socket.gethostname()
host = 'localhost'
port = 8888                  # The same port as used by the server
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((host, port))

# command = {"roi": [0, 0, 0, 0], "command": "stop"}
# command = {'msg': 'ACTIVATE GRID', 'args': [0]}
# command = {'msg': 'ADD GRID', 'args': [23, 0, 150, 200]}
# command = {'msg': 'DELETE GRID'}
# command = {'msg': 'CHANGE GRID ROTATION', 'args': [0, 0, 0]}
command = {'msg': 'GET OV COORDS', 'args': [0]}
# command = {'msg': 'PAUSE', 'args': [2]}
# command = {'msg': 'REMOTE STOP'}


s.sendall(json.dumps(command).encode('utf-8'))
data = s.recv(1024)
s.close()
print('Received', repr(data))