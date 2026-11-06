"""Funções auxiliares para empacotar e interpretar mensagens UDP."""

TAM_BUFFER = 65535


def montar(*campos):
    """Cria um pacote textual a partir de campos separados por '|'."""
    texto = "|".join(str(campo) for campo in campos)
    return texto.encode("utf-8")


def ler(pacote):
    """Lê um pacote textual e retorna a lista de campos."""
    if pacote is None:
        return []

    if isinstance(pacote, bytes):
        pacote = pacote.decode("utf-8", errors="strict")

    texto = pacote.strip()
    if not texto:
        return []

    return texto.split("|")