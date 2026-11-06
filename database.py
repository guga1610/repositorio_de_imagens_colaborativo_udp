# Registrar usuários, arquivos e histórico
import sqlite3
import hashlib
import threading
import os
from datetime import datetime

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_DB = os.path.join(PASTA, "repository.db")

# o servidor tem uma thread por cliente, entao so uma pode mexer no banco por vez
trava = threading.Lock()


def conectar():
    return sqlite3.connect(ARQUIVO_DB)


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def criar_tabelas():
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT PRIMARY KEY,
            senha_hash TEXT NOT NULL,
            criado_em TEXT
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS imagens (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            autor TEXT NOT NULL,
            tamanho INTEGER,
            data_envio TEXT,
            caminho TEXT,
            caminho_thumb TEXT
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            usuario TEXT,
            acao TEXT,
            imagem_id TEXT
        )""")
        con.commit()
        con.close()


def hash_senha(senha):
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()


def usuario_existe(nome):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT nome FROM usuarios WHERE nome = ?", (nome,))
        linha = cur.fetchone()
        con.close()
    return linha is not None


def cadastrar_usuario(nome, senha):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("INSERT INTO usuarios (nome, senha_hash, criado_em) VALUES (?, ?, ?)",
                    (nome, hash_senha(senha), agora()))
        con.commit()
        con.close()


def senha_confere(nome, senha):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT senha_hash FROM usuarios WHERE nome = ?", (nome,))
        linha = cur.fetchone()
        con.close()
    if linha is None:
        return False
    return linha[0] == hash_senha(senha)


def registrar_imagem(id_img, nome, autor, tamanho, caminho, caminho_thumb):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("INSERT INTO imagens (id, nome, autor, tamanho, data_envio, caminho, caminho_thumb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (id_img, nome, autor, tamanho, agora(), caminho, caminho_thumb))
        con.commit()
        con.close()


def imagem_existe(id_img):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT id FROM imagens WHERE id = ?", (id_img,))
        linha = cur.fetchone()
        con.close()
    return linha is not None


def listar_imagens():
    with trava:
        con = conectar()
        cur = con.cursor()
        # essa ordem de colunas e a mesma da linha que o servidor manda no LIST
        cur.execute("SELECT id, nome, autor, data_envio, tamanho FROM imagens ORDER BY data_envio DESC")
        imagens = cur.fetchall()
        con.close()
    return imagens


def buscar_imagem(chave):
    with trava:
        con = conectar()
        cur = con.cursor()
        # aceita id ou nome. se o nome repetir pega a mais recente
        cur.execute("SELECT id, nome, caminho, caminho_thumb FROM imagens WHERE id = ? OR nome = ? ORDER BY data_envio DESC LIMIT 1",
                    (chave, chave))
        imagem = cur.fetchone()
        con.close()
    return imagem


def registrar_acao(usuario, acao, imagem_id=""):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("INSERT INTO historico (data, usuario, acao, imagem_id) VALUES (?, ?, ?, ?)",
                    (agora(), usuario, acao, imagem_id))
        con.commit()
        con.close()


def ultimas_acoes(qtd=20):
    with trava:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT data, usuario, acao, imagem_id FROM historico ORDER BY id DESC LIMIT ?", (qtd,))
        acoes = cur.fetchall()
        con.close()
    return acoes
