# Criar o servidor UDP e atender clientes

import socket

HOST = "0.0.0.0"
PORT = 5000

server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

server.bind((HOST, PORT))

print(f"Servidor UDP iniciado na porta {PORT}")

# no UDP nao tem accept(), cada mensagem chega com o endereco de quem mandou
while True:
    dados, addr = server.recvfrom(2048)

    print(f"Mensagem de {addr}: {dados.decode()}")

    server.sendto(b"Mensagem recebida!", addr)
