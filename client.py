# Enviar comandos para o servidor e receber as respostas

import socket

HOST = "127.0.0.1"
PORT = 5000

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# se a resposta se perder o recvfrom ficaria esperando pra sempre
client.settimeout(3)

client.sendto(b"OLA", (HOST, PORT))

try:
    resposta, addr = client.recvfrom(2048)
    print(resposta.decode())
except socket.timeout:
    print("Servidor nao respondeu")

client.close()
