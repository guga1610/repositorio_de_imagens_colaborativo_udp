import socket
import threading
import time

import protocol
import transfer
import storage
import database

HOST = "0.0.0.0"
PORT = 5000
LIMITE_UPLOAD = 10 * 1024 * 1024
USUARIO_PADRAO = "anonimo"
MAX_PEDIDOS = 64
GUARDA_REENVIO = 0.05
JANELA_REENVIO = 2.5
GUARDA_CONCLUIDO = 0.3
ESPERA_PRONTO = 5.0
TEMPO_FIM = 3.0
ESPERA_FIM = 5.0
TEMPO_SESSAO = 3600

UPLOAD_DEVOLVE_HASH_COMPLETO = True

trava = threading.Lock()
sessoes = {}
pedidos = {}
vagas = threading.BoundedSemaphore(MAX_PEDIDOS)


def ignorar_reset_udp(sock):
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (OSError, ValueError):
            pass


class SocketSessao:

    def __init__(self, ped):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((HOST, 0))
        ignorar_reset_udp(self._sock)
        self._ped = ped

    def recvfrom(self, tamanho):
        dados, origem = self._sock.recvfrom(tamanho)
        if origem == self._ped.addr:
            self._ped.confirmar()
        return dados, origem

    def __getattr__(self, nome):
        return getattr(self._sock, nome)


class Pedido:

    def __init__(self, addr, pacote, principal):
        self.addr = addr
        self.pacote = pacote
        self.principal = principal
        self.sock_sessao = None
        self.resposta = None
        self.sock_resposta = None
        self.por_sessao = False
        self.enviado_em = 0.0
        self.confirmado = False
        self.concluido = False
        self.atualizado = time.monotonic()

    def abrir_sessao(self):
        self.sock_sessao = SocketSessao(self)
        return self.sock_sessao

    def fechar_sessao(self):
        if self.sock_sessao is not None:
            self.sock_sessao.close()

    def responder(self, pacote, sock=None):
        self.resposta = pacote
        self.sock_resposta = sock or self.principal
        self.por_sessao = sock is not None
        self.confirmado = False
        self._enviar()

    def confirmar(self):
        self.confirmado = True

    def ao_repetir(self):
        agora = time.monotonic()
        if self.resposta is None:
            return "ignorar"

        if self.por_sessao:
            if not self.confirmado:
                if self.concluido:
                    return "novo"
                return "reenviar" if agora - self.enviado_em >= GUARDA_REENVIO else "ignorar"

            if not self.concluido or agora - self.atualizado < GUARDA_CONCLUIDO:
                return "ignorar"
            return "novo"

        idade = agora - self.enviado_em
        if idade < GUARDA_REENVIO:
            return "ignorar"
        if idade < JANELA_REENVIO:
            return "reenviar"
        return "novo"

    def reenviar(self):
        self._enviar()

    def _enviar(self):
        self.enviado_em = time.monotonic()
        try:
            self.sock_resposta.sendto(self.resposta, self.addr)
        except OSError:
            pass

    def finalizar(self):
        self.concluido = True
        self.atualizado = time.monotonic()


def limpar_motivo(texto):
    return str(texto).replace("|", "/").replace("\r", " ").replace("\n", " ")


def erro(ped, motivo, sock=None):
    ped.responder(protocol.montar("ERRO", limpar_motivo(motivo)), sock)


def ok(ped, *campos, sock=None):
    ped.responder(protocol.montar("OK", *campos), sock)


def usuario_da_sessao(addr):
    with trava:
        sessao = sessoes.get(addr)
        if sessao is None:
            return USUARIO_PADRAO
        sessoes[addr] = (sessao[0], time.monotonic())
        return sessao[0]


def guardar_sessao(addr, usuario):
    with trava:
        sessoes[addr] = (usuario, time.monotonic())


def usuario_valido(usuario):
    if not usuario or usuario in (".", "..") or len(usuario) > 50 or usuario != usuario.strip():
        return False
    return not any(c in usuario for c in "/\\\x00")


def cmd_login(ped, partes):
    if len(partes) != 3 or not partes[1] or not partes[2]:
        erro(ped, "uso: LOGIN|usuario|senha")
        return

    usuario, senha = partes[1], partes[2]
    if not usuario_valido(usuario) or usuario == USUARIO_PADRAO:
        erro(ped, "nome de usuario invalido")
        return

    if database.usuario_existe(usuario):
        if not database.senha_confere(usuario, senha):
            erro(ped, "senha incorreta")
            return
        mensagem = "bem-vindo de volta, " + usuario
    else:
        try:
            database.cadastrar_usuario(usuario, senha)
        except Exception:
            if not database.senha_confere(usuario, senha):
                erro(ped, "senha incorreta")
                return
            mensagem = "bem-vindo de volta, " + usuario
        else:
            mensagem = "usuario cadastrado, " + usuario

    guardar_sessao(ped.addr, usuario)
    database.registrar_acao(usuario, "LOGIN")
    ok(ped, mensagem)


def esvaziar(sock):
    sock.setblocking(False)
    try:
        while True:
            sock.recvfrom(protocol.TAM_BUFFER)
    except OSError:
        pass


def eh_fim(pacote):
    return not protocol.eh_transferencia(pacote) and protocol.ler(pacote)[0] == "FIM"


def reconfirmar(sock, addr, pacote):
    try:
        if pacote.startswith(protocol.FIM_ARQUIVO):
            sock.sendto(protocol.ARQUIVO_OK, addr)
        elif pacote.startswith(protocol.QUADRO):
            quadro = transfer._ler_quadro(pacote)
            if quadro is not None:
                sock.sendto(transfer._ack(quadro[0]), addr)
    except OSError:
        pass


def aguardar_fim(sock, addr):
    limite = time.monotonic() + ESPERA_FIM
    while time.monotonic() < limite:
        sock.settimeout(0.5)
        try:
            pacote, origem = sock.recvfrom(protocol.TAM_BUFFER)
        except socket.timeout:
            continue
        except OSError:
            continue
        if origem != addr:
            continue
        if eh_fim(pacote):
            return True
        reconfirmar(sock, addr, pacote)
    return False


def manter_fim(sock, addr, resposta_final):
    limite = time.monotonic() + TEMPO_FIM
    ultimo_envio = time.monotonic()
    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            return
        sock.settimeout(restante)
        try:
            pacote, origem = sock.recvfrom(protocol.TAM_BUFFER)
        except socket.timeout:
            return
        except OSError:
            continue
        if origem != addr or not eh_fim(pacote):
            continue
        if time.monotonic() - ultimo_envio < GUARDA_REENVIO:
            continue
        try:
            sock.sendto(resposta_final, addr)
        except OSError:
            pass
        ultimo_envio = time.monotonic()


def salvar_upload(usuario, nome, dados):
    try:
        if not storage.eh_imagem(dados):
            return protocol.montar("ERRO", "o arquivo nao e uma imagem valida")
        if database.imagem_existe(storage.gerar_id(dados)):
            return protocol.montar("ERRO", "essa imagem ja foi enviada")
        try:
            id_img, nome, tamanho, caminho, caminho_thumb = storage.salvar_imagem(usuario, nome, dados)
        except ValueError as e:
            return protocol.montar("ERRO", limpar_motivo(e))
        database.registrar_imagem(id_img, nome, usuario, tamanho, caminho, caminho_thumb)
        database.registrar_acao(usuario, "UPLOAD", id_img)
        identificador = transfer.resumo(dados) if UPLOAD_DEVOLVE_HASH_COMPLETO else id_img
        return protocol.montar("OK", identificador)
    except Exception as e:
        print(f"Erro ao salvar upload: {e}")
        return protocol.montar("ERRO", "erro interno do servidor")


def cmd_upload(ped, partes, usuario):
    if len(partes) != 3:
        erro(ped, "uso: UPLOAD|nome|tamanho")
        return

    try:
        tamanho = int(partes[2])
    except ValueError:
        erro(ped, "tamanho invalido")
        return

    try:
        nome = storage.limpar_nome(partes[1])
    except ValueError:
        erro(ped, "nome do arquivo invalido")
        return

    if not storage.extensao_valida(nome):
        erro(ped, "extensao de imagem nao permitida")
        return
    if tamanho <= 0:
        erro(ped, "arquivo vazio")
        return
    if tamanho > LIMITE_UPLOAD:
        erro(ped, "arquivo maior que 10 MB")
        return

    sock = ped.abrir_sessao()
    ok(ped, "pode enviar", sock=sock)

    dados = transfer.receber_arquivo(sock, ped.addr, tamanho)
    if dados is None:
        print(f"Upload de {ped.addr} interrompido: cliente parou de enviar ou o hash nao confere")
        return

    if not aguardar_fim(sock, ped.addr):
        print(f"Upload de {ped.addr}: cliente nao pediu o resultado")
        return

    esvaziar(sock)

    if len(dados) != tamanho:
        resposta_final = protocol.montar("ERRO", "tamanho recebido diferente do informado")
    else:
        resposta_final = salvar_upload(usuario, nome, dados)

    esvaziar(sock)
    sock.sendto(resposta_final, ped.addr)
    ped.finalizar()
    manter_fim(sock, ped.addr, resposta_final)


def esperar_pronto(sock, addr):
    pronto = protocol.montar("PRONTO")
    limite = time.monotonic() + ESPERA_PRONTO

    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            return False

        pacote = transfer.receber_de(sock, addr, timeout=restante)
        if pacote is None:
            return False
        if pacote == pronto:
            return True


def enviar_dados(ped, dados, nome):
    sock = ped.abrir_sessao()
    ok(ped, len(dados), limpar_motivo(nome), transfer.resumo(dados), sock=sock)

    if not esperar_pronto(sock, ped.addr):
        print(f"{ped.addr}: cliente nao confirmou o recebimento de {nome}")
        return False

    if not dados:
        return True

    if not transfer.enviar_arquivo(sock, ped.addr, dados):
        print(f"{ped.addr}: transferencia de {nome} nao foi concluida")
        return False

    return True


def cmd_list(ped, usuario):
    imagens = database.listar_imagens()
    linhas = [f"{id_img} | {nome} | {autor} | {data} | {tamanho} bytes"
              for id_img, nome, autor, data, tamanho in imagens]
    texto = "\n".join(linhas).encode("utf-8")

    if enviar_dados(ped, texto, "lista"):
        database.registrar_acao(usuario, "LIST")


def cmd_hist(ped):
    acoes = database.ultimas_acoes(20)
    linhas = [f"{data} | {quem} | {acao} | {id_img or ''}" for data, quem, acao, id_img in acoes]
    texto = "\n".join(linhas).encode("utf-8")
    enviar_dados(ped, texto, "historico")


def normalizar_chave(chave):
    if len(chave) == 64 and all(c in "0123456789abcdefABCDEF" for c in chave):
        return chave[:12].lower()
    return chave


def cmd_baixar(ped, partes, usuario, miniatura):
    acao = "VIEW" if miniatura else "DOWNLOAD"

    if len(partes) != 2 or not partes[1]:
        erro(ped, "uso: " + acao + "|id ou nome")
        return

    imagem = database.buscar_imagem(normalizar_chave(partes[1]))
    if imagem is None:
        erro(ped, "imagem nao encontrada")
        return

    id_img, nome, caminho, caminho_thumb = imagem

    try:
        dados = storage.ler_arquivo(caminho_thumb if miniatura else caminho)
    except OSError:
        erro(ped, "arquivo nao encontrado no disco")
        return

    if len(dados) > LIMITE_UPLOAD:
        erro(ped, "imagem maior que o limite de 10 MB do cliente UDP")
        return

    nome_envio = id_img + ".jpg" if miniatura else nome

    if enviar_dados(ped, dados, nome_envio):
        database.registrar_acao(usuario, acao, id_img)


def processar(ped):
    try:
        partes = protocol.ler(ped.pacote)
        comando = partes[0].upper()
        usuario = usuario_da_sessao(ped.addr)

        print(f"{ped.addr[0]}:{ped.addr[1]} -> {comando[:20].encode('unicode_escape').decode()} (usuario: {usuario})")

        if comando == "LOGIN":
            cmd_login(ped, partes)
        elif comando == "UPLOAD":
            cmd_upload(ped, partes, usuario)
        elif comando == "LIST":
            cmd_list(ped, usuario)
        elif comando == "DOWNLOAD":
            cmd_baixar(ped, partes, usuario, miniatura=False)
        elif comando == "VIEW":
            cmd_baixar(ped, partes, usuario, miniatura=True)
        elif comando == "HIST":
            cmd_hist(ped)
        else:
            erro(ped, "comando desconhecido")

    except Exception as e:
        print(f"Erro com {ped.addr}: {e}")
        if ped.resposta is None:
            erro(ped, "erro interno do servidor")

    finally:
        ped.fechar_sessao()
        ped.finalizar()
        vagas.release()


def receber_pedido(servidor, pacote, addr):
    if not pacote or protocol.eh_transferencia(pacote):
        return

    if protocol.ler(pacote)[0].upper() in ("FIM", "PRONTO"):
        return

    chave = (addr, pacote)

    with trava:
        ped = pedidos.get(chave)
        acao = ped.ao_repetir() if ped is not None else "novo"

        if acao == "novo":
            ped = Pedido(addr, pacote, servidor)
            pedidos[chave] = ped

    if acao == "reenviar":
        ped.reenviar()
        return

    if acao == "ignorar":
        return

    if not vagas.acquire(blocking=False):
        with trava:
            pedidos.pop(chave, None)
        servidor.sendto(protocol.montar("ERRO", "servidor ocupado, tente de novo"), addr)
        return

    threading.Thread(target=processar, args=(ped,), daemon=True).start()


def limpar_antigos():
    agora = time.monotonic()

    with trava:
        for chave in [c for c, p in pedidos.items() if p.concluido and agora - p.atualizado > 30]:
            del pedidos[chave]

        for addr in [a for a, s in sessoes.items() if agora - s[1] > TEMPO_SESSAO]:
            del sessoes[addr]


def main():
    database.criar_tabelas()

    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.bind((HOST, PORT))
    servidor.settimeout(1.0)
    ignorar_reset_udp(servidor)

    print(f"Servidor UDP iniciado na porta {PORT}")

    ultima_limpeza = time.monotonic()

    try:
        while True:
            try:
                pacote, addr = servidor.recvfrom(protocol.TAM_BUFFER)
            except socket.timeout:
                pacote = None
            except OSError:
                pacote = None

            if pacote is not None:
                receber_pedido(servidor, pacote, addr)

            if time.monotonic() - ultima_limpeza > 5:
                limpar_antigos()
                ultima_limpeza = time.monotonic()

    except KeyboardInterrupt:
        print("\nServidor encerrado.")

    finally:
        servidor.close()


if __name__ == "__main__":
    main()