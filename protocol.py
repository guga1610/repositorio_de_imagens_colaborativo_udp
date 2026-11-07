
SEPARADOR = "|"
TAM_BUFFER = 65535   

QUADRO = b"FRM"
ACK = b"ACK"
FIM_ARQUIVO = b"EOF"
ARQUIVO_OK = b"OKF"
ARQUIVO_ERRO = b"ERR"
TAM_ACK = len(ACK) + 4


def montar(*campos):
    """Junta os campos com | e devolve bytes. Ex: montar("OK", 12) -> b"OK|12"."""
    return SEPARADOR.join(str(c) for c in campos).encode("utf-8")


def ler(pacote):
    """Separa um pacote de texto em campos. Nunca da erro e sempre devolve pelo menos 1 campo
    (o client.py le resposta[0] direto, entao uma lista vazia quebraria ele)."""
    if pacote is None:
        return [""]
    if isinstance(pacote, (bytes, bytearray)):
        pacote = bytes(pacote).decode("utf-8", errors="replace")
    return pacote.rstrip("\r\n").split(SEPARADOR)


def eh_transferencia(pacote):
    """True se o pacote e da transferencia de arquivo (e nao um comando de texto).
    OKF e ERR so contam quando sao o pacote inteiro, para nao confundir com ERRO|motivo."""
    return (pacote.startswith((QUADRO, FIM_ARQUIVO))
            or (pacote.startswith(ACK) and len(pacote) == TAM_ACK)
            or pacote in (ARQUIVO_OK, ARQUIVO_ERRO))
