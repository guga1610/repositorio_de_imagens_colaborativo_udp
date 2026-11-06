import hashlib
import random
import socket
import struct


TAM_MAX_PACOTE = 1400
TIMEOUT_PADRAO = 0.5


def resumo(dados):
    """Calcula o resumo criptográfico dos dados recebidos."""
    if isinstance(dados, str):
        dados = dados.encode("utf-8")
    return hashlib.sha256(dados).hexdigest()


def enviar(sock, destino, pacote, perda=0.0):
    """Envia um pacote UDP, simulando perda de datagrama opcionalmente."""
    if pacote is None:
        return False

    if isinstance(pacote, str):
        pacote = pacote.encode("utf-8")

    if perda and random.random() < perda:
        return False

    sock.sendto(pacote, destino)
    return True


def receber_de(sock, origem, timeout=TIMEOUT_PADRAO):
    """Recebe um pacote UDP de uma origem específica."""
    sock.settimeout(timeout)

    while True:
        try:
            dados, endereco = sock.recvfrom(65535)
        except socket.timeout:
            return None

        if origem is None or endereco == origem:
            return dados


def _montar_quadro(seq, dados):
    """Cria um quadro de arquivo com cabeçalho de número e tamanho."""
    payload = b"" if dados is None else dados
    header = struct.pack("!II", seq, len(payload))
    return b"FRM" + header + payload


def _ler_quadro(pacote):
    """Interpreta um quadro de arquivo."""
    if len(pacote) < 10 or pacote[:3] != b"FRM":
        return None

    seq, tamanho = struct.unpack("!II", pacote[3:11])
    dados = pacote[11:]

    if len(dados) != tamanho:
        return None

    return seq, dados


def _ack(seq):
    return b"ACK" + struct.pack("!I", seq)


def _fim(hash_arquivo):
    return b"EOF" + hash_arquivo.encode("utf-8")


def enviar_arquivo(sock, destino, dados, bloco=TAM_MAX_PACOTE, perda=0.0, timeout=TIMEOUT_PADRAO, max_tentativas=20):
    """Envia um arquivo em blocos com ACK, retransmissão e espera final."""
    if dados is None:
        return False

    if isinstance(dados, str):
        dados = dados.encode("utf-8")

    total = len(dados)
    if total == 0:
        return False

    blocos = [dados[i:i + bloco] for i in range(0, total, bloco)]

    for indice, bloco_dados in enumerate(blocos):
        pacote = _montar_quadro(indice, bloco_dados)

        for tentativa in range(max_tentativas):
            if not enviar(sock, destino, pacote, perda=perda):
                continue

            ack = receber_de(sock, destino, timeout=timeout)
            if ack == _ack(indice):
                break

            if tentativa == max_tentativas - 1:
                return False

    hash_arquivo = resumo(dados)
    fim = _fim(hash_arquivo)
    for tentativa in range(max_tentativas):
        if not enviar(sock, destino, fim, perda=perda):
            continue

        resposta = receber_de(sock, destino, timeout=timeout)
        if resposta == b"OKF":
            return True

        if tentativa == max_tentativas - 1:
            return False

    return True


def receber_arquivo(sock, origem, tamanho, timeout=TIMEOUT_PADRAO, max_tentativas=20):
    """Recebe um arquivo em blocos e reconstitui o conteúdo em ordem."""
    if tamanho <= 0:
        return b""

    buffer = {}
    total = 0

    while True:
        pacote = receber_de(sock, origem, timeout=timeout)
        if pacote is None:
            if max_tentativas <= 0:
                return None
            max_tentativas -= 1
            continue

        if pacote.startswith(b"FRM"):
            quadro = _ler_quadro(pacote)
            if quadro is None:
                continue

            seq, dados = quadro
            if seq not in buffer:
                buffer[seq] = dados
                total += len(dados)
                sock.sendto(_ack(seq), origem)
            else:
                sock.sendto(_ack(seq), origem)
            continue

        if pacote.startswith(b"EOF"):
            esperado = pacote[3:]
            dados = b"".join(buffer[i] for i in sorted(buffer))
            hash_arquivo = resumo(dados)

            if esperado.decode("utf-8", errors="ignore") == hash_arquivo:
                sock.sendto(b"OKF", origem)
                return dados[:tamanho]

            sock.sendto(b"ERR", origem)
            return None

