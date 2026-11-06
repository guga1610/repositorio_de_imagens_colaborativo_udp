"""Validação e armazenamento das imagens originais do repositório."""

import hashlib
import io
import threading
from pathlib import Path

from PIL import Image


PASTA = Path(__file__).resolve().parent
PASTA_UPLOADS = PASTA / "uploads"
PASTA_THUMBNAILS = PASTA / "thumbnails"
TAMANHO_MAXIMO = 20 * 1024 * 1024
TAMANHO_MINIATURA = (128, 128)
EXTENSOES_VALIDAS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_trava_salvamento = threading.Lock()


def limpar_nome(nome):
    """Retorna apenas o nome do arquivo e recusa nomes inválidos no protocolo."""
    if not isinstance(nome, str):
        raise ValueError("nome do arquivo inválido")

    nome = nome.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not nome or nome in {".", ".."} or "|" in nome or "\x00" in nome:
        raise ValueError("nome do arquivo inválido")
    return nome


def extensao_valida(nome):
    """Informa se o nome possui uma extensão de imagem aceita."""
    try:
        nome = limpar_nome(nome)
    except ValueError:
        return False
    return Path(nome).suffix.lower() in EXTENSOES_VALIDAS


def _bytes_arquivo(arquivo):
    """Converte bytes ou um caminho para o conteúdo do arquivo."""
    if isinstance(arquivo, (bytes, bytearray, memoryview)):
        return bytes(arquivo)
    with open(arquivo, "rb") as entrada:
        return entrada.read()


def eh_imagem(arquivo):
    """Valida o conteúdo com Pillow, sem confiar apenas na extensão."""
    try:
        conteudo = _bytes_arquivo(arquivo)
        if not conteudo or len(conteudo) > TAMANHO_MAXIMO:
            return False
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.verify()
        return True
    except (OSError, ValueError, TypeError, Image.DecompressionBombError):
        return False


def gerar_id(conteudo):
    """Gera o identificador com os 12 primeiros caracteres do SHA-256."""
    if not isinstance(conteudo, (bytes, bytearray, memoryview)):
        raise TypeError("o conteúdo deve ser bytes")
    return hashlib.sha256(conteudo).hexdigest()[:12]


def gerar_miniatura(conteudo, usuario, id_img):
    """Cria uma miniatura JPEG de até 128x128 em thumbnails/<usuario>/.

    A proporção da imagem é preservada. Imagens com transparência são convertidas
    para RGB antes de salvar, pois JPEG não oferece suporte a canal alfa.
    """
    pasta_usuario = PASTA_THUMBNAILS / _limpar_usuario(usuario)
    pasta_usuario.mkdir(parents=True, exist_ok=True)
    caminho = pasta_usuario / (id_img + ".jpg")

    criado = False
    try:
        with Image.open(io.BytesIO(bytes(conteudo))) as imagem:
            imagem.thumbnail(TAMANHO_MINIATURA)
            miniatura = imagem.convert("RGB")
            with caminho.open("xb") as saida:
                criado = True
                miniatura.save(saida, format="JPEG")
    except Exception:
        if criado:
            caminho.unlink(missing_ok=True)
        raise

    return str(caminho)


def _limpar_usuario(usuario):
    if not isinstance(usuario, str):
        raise ValueError("usuário inválido")
    usuario = usuario.strip()
    if (not usuario or usuario in {".", ".."} or "|" in usuario
            or "/" in usuario or "\\" in usuario or "\x00" in usuario):
        raise ValueError("usuário inválido")
    return usuario


def salvar_imagem(usuario, nome, conteudo):
    """Valida e grava uma imagem original em uploads/<usuario>/<id><extensão>.

    Retorna (id, nome_original, tamanho, caminho, caminho_thumb). Rejeita arquivos
    inválidos, maiores que 20 MiB e conteúdo já armazenado.
    """
    usuario = _limpar_usuario(usuario)
    nome = limpar_nome(nome)
    if not extensao_valida(nome):
        raise ValueError("extensão de imagem inválida")
    if not isinstance(conteudo, (bytes, bytearray, memoryview)):
        raise TypeError("o conteúdo deve ser bytes")
    conteudo = bytes(conteudo)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise ValueError("imagem excede o limite de 20 MB")
    if not eh_imagem(conteudo):
        raise ValueError("arquivo não contém uma imagem válida")

    id_img = gerar_id(conteudo)
    pasta_usuario = PASTA_UPLOADS / usuario
    pasta_usuario.mkdir(parents=True, exist_ok=True)
    caminho = pasta_usuario / (id_img + Path(nome).suffix.lower())
    # O identificador é global no banco; bloquear duplicatas também entre usuários
    # e extensões diferentes evita colisão com a chave primária de imagens.
    # A busca e a criação precisam ser serializadas: IDs iguais com extensões
    # ou usuários diferentes poderiam passar pela busca ao mesmo tempo.
    with _trava_salvamento:
        if any(PASTA_UPLOADS.glob(f"*/{id_img}.*")):
            raise ValueError("esta imagem já foi enviada")
        try:
            with caminho.open("xb") as saida:
                saida.write(conteudo)
        except FileExistsError as erro:
            raise ValueError("esta imagem já foi enviada") from erro
    try:
        caminho_thumb = gerar_miniatura(conteudo, usuario, id_img)
    except Exception:
        caminho.unlink(missing_ok=True)
        raise
    return id_img, nome, len(conteudo), str(caminho), caminho_thumb


def ler_arquivo(caminho):
    """Lê e devolve os bytes de um arquivo armazenado."""
    with open(caminho, "rb") as arquivo:
        return arquivo.read()
