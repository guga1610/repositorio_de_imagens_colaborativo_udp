
import socket
import os
import sys
import argparse
from pathlib import Path
from getpass import getpass

import protocol
import transfer

PORTA = 5000
TAM_MAX = 10 * 1024 * 1024
MAX_TENTATIVAS = 20
TIMEOUT = 0.1

PASTA_DOWNLOADS = Path("downloads")

# counicação udp
def pedir(sock, destino, pacote):
    """
    Envia um pedido UDP e espera uma resposta.

    Reenvia o pedido até MAX_TENTATIVAS vezes caso não
    receba resposta.

    Retorna:
        (resposta, endereco) ou None
    """

    sock.settimeout(TIMEOUT)

    for tentativa in range(MAX_TENTATIVAS):
        try:
            sock.sendto(pacote, destino)

            while True:
                resposta, endereco = sock.recvfrom(protocol.TAM_BUFFER)

                if endereco[0] != destino[0]:
                    continue

                if destino[1] != PORTA and endereco != destino:
                    continue

                return resposta, endereco

        except socket.timeout:
            print(
                f"Sem resposta. Tentativa "
                f"{tentativa + 1}/{MAX_TENTATIVAS}..."
            )

    print("Servidor não respondeu após 20 tentativas.")
    return None


def interpretar_pacote(pacote):
    """Converte um pacote de texto em seus campos."""

    try:
        return protocol.ler(pacote)
    except Exception as erro:
        print(f"Erro ao interpretar pacote: {erro}")
        return []


def enviar_comando(sock, destino, *campos):
    """
    Monta e envia um comando ao servidor.

    Retorna a resposta e o endereço que respondeu.
    """

    pacote = protocol.montar(*campos)
    resultado = pedir(sock, destino, pacote)

    if resultado is None:
        return None, None

    resposta, endereco = resultado
    campos_resposta = interpretar_pacote(resposta)

    return campos_resposta, endereco


# login
def fazer_login(sock, servidor):
    print("\n========== LOGIN ==========")

    usuario = input("Usuário: ").strip()
    senha = getpass("Senha: ")

    if not usuario or not senha:
        print("Usuário e senha não podem ficar vazios.")
        return

    resposta, endereco = enviar_comando(
        sock,
        servidor,
        "LOGIN",
        usuario,
        senha
    )

    if resposta is None:
        return

    if resposta[0] == "OK":
        print("Login realizado com sucesso!")
        if len(resposta) > 1:
            print(resposta[1])

    else:
        print("Erro no login:", "|".join(resposta[1:]))


# upload
def upload(sock, servidor):
    print("\n========== UPLOAD ==========")

    caminho = input("Caminho da imagem: ").strip().strip('"')

    arquivo = Path(caminho)

    if not arquivo.is_file():
        print("Arquivo não encontrado.")
        return

    nome = arquivo.name

    if "|" in nome or "\n" in nome or "\r" in nome:
        print("O nome do arquivo não pode conter | ou quebras de linha.")
        return

    try:
        tamanho = arquivo.stat().st_size

        if tamanho <= 0:
            print("O arquivo está vazio.")
            return

        if tamanho > TAM_MAX:
            print("O arquivo ultrapassa o limite de 10 MB.")
            return

        with open(arquivo, "rb") as f:
            dados = f.read()

    except OSError as erro:
        print(f"Erro ao ler arquivo: {erro}")
        return

    # calcula o hash antes de enviar
    hash_original = transfer.resumo(dados)

    print(f"Enviando {nome} ({tamanho} bytes)...")

    # solicita autorização ao servidor
    resposta, endereco = enviar_comando(
        sock,
        servidor,
        "UPLOAD",
        nome,
        str(tamanho)
    )

    if resposta is None:
        return

    if resposta[0] != "OK":
        print("Upload recusado:", "|".join(resposta[1:]))
        return

    if len(resposta) < 2 or resposta[1] != "pode enviar":
        print("Resposta inesperada do servidor.")
        return

    # envia os dados utilizando stop-and-wait
    sucesso = transfer.enviar_arquivo(sock, endereco, dados)

    if not sucesso:
        print("Falha durante a transferência do arquivo.")
        return

    # após o último ACK solicita o resultado do upload
    resultado = pedir(
        sock,
        endereco,
        protocol.montar("FIM")
    )

    if resultado is None:
        print("Não foi possível obter o resultado do upload.")
        return

    pacote_final, endereco_final = resultado
    resposta_final = interpretar_pacote(pacote_final)

    if not resposta_final:
        print("Resposta final inválida.")
        return

    if resposta_final[0] == "OK":
        if len(resposta_final) > 1:
            identificador = resposta_final[1]

            if identificador != hash_original:
                print("ERRO: o hash retornado não confere!")
                print("Arquivo enviado pode ter sido corrompido.")
                return

            print("Upload realizado com sucesso!")
            print("ID da imagem:", identificador)
        else:
            print("Upload concluído, mas o servidor não retornou o ID.")

    else:
        print("Erro no upload:", "|".join(resposta_final[1:]))


# recebimento de arquivos
def receber_arquivo(sock, endereco, tamanho, hash_esperado):
    """
    Autoriza o envio e recebe um arquivo usando transfer.py.
    Depois confere o hash do conteúdo recebido.
    """

    transfer.enviar(
        sock,
        endereco,
        protocol.montar("PRONTO")
    )

    dados = transfer.receber_arquivo(
        sock,
        endereco,
        tamanho
    )

    if dados is None:
        print("Falha ao receber o arquivo.")
        return None

    hash_recebido = transfer.resumo(dados)

    if hash_recebido != hash_esperado:
        print("ERRO: hash não confere!")
        print("O arquivo recebido pode estar corrompido.")
        return None

    return dados


def salvar_arquivo(nome, dados):
    """Salva os dados recebidos na pasta downloads."""

    PASTA_DOWNLOADS.mkdir(exist_ok=True)

    # evita caminhos maliciosos ou nomes com diretórios
    nome_seguro = Path(nome).name

    if not nome_seguro:
        nome_seguro = "arquivo_recebido"

    destino = PASTA_DOWNLOADS / nome_seguro

    try:
        with open(destino, "wb") as f:
            f.write(dados)

        print(f"Arquivo salvo em: {destino.resolve()}")
        return destino

    except OSError as erro:
        print(f"Erro ao salvar arquivo: {erro}")
        return None


# listagem
def listar_imagens(sock, servidor):
    print("\n========== IMAGENS DISPONÍVEIS ==========")

    resposta, endereco = enviar_comando(
        sock,
        servidor,
        "LIST"
    )

    if resposta is None:
        return

    if resposta[0] == "ERRO":
        print("Erro:", "|".join(resposta[1:]))
        return

    # formato esperado: OK|tamanho|lista|hash
    if len(resposta) < 4 or resposta[0] != "OK":
        print("Resposta de listagem inválida.")
        return

    try:
        tamanho = int(resposta[1])
        hash_esperado = resposta[3]
    except ValueError:
        print("Tamanho da listagem inválido.")
        return

    dados = receber_arquivo(
        sock,
        endereco,
        tamanho,
        hash_esperado
    )

    if dados is None:
        return

    texto = dados.decode("utf-8", errors="replace")

    if not texto.strip():
        print("Nenhuma imagem cadastrada.")
        return

    print("\nID | Nome | Autor | Data | Tamanho")
    print("-" * 75)
    print(texto)


# download e view
def baixar_arquivo(sock, servidor, operacao):
    if operacao == "DOWNLOAD":
        print("\n========== DOWNLOAD ==========")
    else:
        print("\n========== VISUALIZAR IMAGEM ==========")

    identificador = input("ID ou nome da imagem: ").strip()

    if not identificador:
        print("Informe um ID ou nome.")
        return

    resposta, endereco = enviar_comando(
        sock,
        servidor,
        operacao,
        identificador
    )

    if resposta is None:
        return

    if resposta[0] == "ERRO":
        print("Erro:", "|".join(resposta[1:]))
        return

    # formato esperado: OK|tamanho|nome|hash
    if len(resposta) < 4 or resposta[0] != "OK":
        print("Resposta inválida do servidor.")
        return

    try:
        tamanho = int(resposta[1])
        nome = resposta[2]
        hash_esperado = resposta[3]
    except ValueError:
        print("Tamanho do arquivo inválido.")
        return

    if tamanho < 0 or tamanho > TAM_MAX:
        print("Tamanho recebido fora do limite permitido.")
        return

    print(f"Recebendo {nome} ({tamanho} bytes)...")

    dados = receber_arquivo(
        sock,
        endereco,
        tamanho,
        hash_esperado
    )

    if dados is None:
        return

    caminho = salvar_arquivo(nome, dados)

    if caminho is None:
        return

    print("Hash conferido. Arquivo recebido corretamente!")

    # na operação VIEW, tenta abrir a miniatura
    if operacao == "VIEW":
        try:
            if sys.platform == "win32":
                os.startfile(caminho)
            elif sys.platform == "darwin":
                os.system(f'open "{caminho}"')
            else:
                os.system(f'xdg-open "{caminho}"')

        except Exception as erro:
            print("Não foi possível abrir a imagem:", erro)


# histórico
def mostrar_historico(sock, servidor):
    print("\n========== HISTÓRICO ==========")

    resposta, endereco = enviar_comando(
        sock,
        servidor,
        "HIST"
    )

    if resposta is None:
        return

    if resposta[0] == "ERRO":
        print("Erro:", "|".join(resposta[1:]))
        return

    # formato esperado: OK|tamanho|historico|hash
    if len(resposta) < 4 or resposta[0] != "OK":
        print("Resposta de histórico inválida.")
        return

    try:
        tamanho = int(resposta[1])
        hash_esperado = resposta[3]
    except ValueError:
        print("Tamanho do histórico inválido.")
        return

    dados = receber_arquivo(
        sock,
        endereco,
        tamanho,
        hash_esperado
    )

    if dados is None:
        return

    texto = dados.decode("utf-8", errors="replace")

    if not texto.strip():
        print("Histórico vazio.")
    else:
        print("\nData | Usuário | Ação | ID")
        print("-" * 60)
        print(texto)


# menu
def executar_cliente(host, porta):
    servidor = (host, porta)

    # um único socket é mantido durante toda a execução, isso preserva o endereço do cliente usado na sessão de login
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    print("======================================")
    print("   REPOSITÓRIO COLABORATIVO DE IMAGENS")
    print("              UDP")
    print("======================================")
    print(f"Servidor: {host}:{porta}")

    try:
        while True:
            print("\n========== MENU ==========")
            print("1 - Login")
            print("2 - Upload de imagem")
            print("3 - Listar imagens")
            print("4 - Download de imagem")
            print("5 - Visualizar imagem")
            print("6 - Histórico")
            print("0 - Sair")

            opcao = input("\nEscolha uma opção: ").strip()

            if opcao == "1":
                fazer_login(sock, servidor)

            elif opcao == "2":
                upload(sock, servidor)

            elif opcao == "3":
                listar_imagens(sock, servidor)

            elif opcao == "4":
                baixar_arquivo(sock, servidor, "DOWNLOAD")

            elif opcao == "5":
                baixar_arquivo(sock, servidor, "VIEW")

            elif opcao == "6":
                mostrar_historico(sock, servidor)

            elif opcao == "0":
                print("Encerrando cliente.")
                break

            else:
                print("Opção inválida. Tente novamente.")

    except KeyboardInterrupt:
        print("\nCliente encerrado pelo usuário.")

    finally:
        sock.close()


# execução
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cliente UDP do repositório colaborativo de imagens"
    )

    parser.add_argument(
        "host",
        nargs="?",
        default="127.0.0.1",
        help="IP do servidor"
    )

    parser.add_argument(
        "porta",
        nargs="?",
        type=int,
        default=PORTA,
        help="Porta do servidor (padrão: 5000)"
    )

    args = parser.parse_args()

    executar_cliente(args.host, args.porta)
