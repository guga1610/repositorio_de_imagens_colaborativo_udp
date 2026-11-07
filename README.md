Sistema distribuído cliente-servidor com Sockets UDP para compartilhamento colaborativo de imagens. Permite upload, armazenamento, listagem, visualização por miniaturas e download, mantendo um histórico com informações sobre autoria, data de envio e tamanho dos arquivos.

APS 02: mesma atividade da APS 01, agora usando UDP. Como o UDP não garante entrega, ordem nem ausência de duplicatas, a confiabilidade é feita na aplicação.


## TECNOLOGIAS USADAS

* socket (SOCK_DGRAM): comunicação UDP
* threading: atender mais de um cliente ao mesmo tempo
* struct: cabeçalho binário dos pacotes de arquivo (número do pedaço e tamanho)
* hashlib: id das imagens, hash das senhas e conferência do arquivo inteiro (sha256)
* sqlite3: banco de dados
* Pillow: validar a imagem e gerar a miniatura
* os e pathlib: arquivos e pastas


## COMO RODAR

Precisa de Python 3.8 ou mais novo. No Mac/Linux o comando costuma ser `python3`; no Windows, `python`.

1. Instalar a dependência (só o Pillow), de preferência num ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Subir o servidor (escuta na porta UDP 5000 e cria o `repository.db` sozinho):

```bash
python3 server.py
```

3. Em outro terminal, abrir o cliente:

```bash
python3 client.py                 # servidor na mesma máquina
python3 client.py 192.168.0.10    # servidor em outra máquina (IP dela)
python3 client.py 192.168.0.10 5000
```

Para rodar em máquinas diferentes, as duas precisam estar na mesma rede e o firewall da máquina do servidor tem que liberar a porta **UDP** 5000. O IP do servidor sai no `ipconfig` (Windows) ou `ifconfig` / `ip a` (Mac/Linux).

Para parar o servidor: Ctrl+C.


## MENU DO CLIENTE

```
1 - Login
2 - Upload de imagem
3 - Listar imagens
4 - Download de imagem
5 - Visualizar imagem
6 - Histórico
0 - Sair
```

* **Login** é opcional. Se o usuário não existe ele é cadastrado na hora; se existe, a senha tem que bater. Sem login, os envios ficam com autor `anonimo`. O servidor lembra do login pelo endereço (ip, porta) do cliente, então vale até fechar o cliente.
* **Upload** pede o caminho da imagem. Aceita `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp` e `.webp`, até 10 MB. No fim mostra o id (sha256) da imagem.
* **Download** e **Visualizar** pedem o id ou o nome da imagem (os dois aparecem no LIST). Se tiver nome repetido, vem a mais recente. O arquivo é salvo na pasta `downloads/`; no Visualizar a miniatura também é aberta.
* **Histórico** mostra as últimas 20 ações (login, upload, list, download, view).


## COMANDOS E RESPOSTAS

Os comandos são texto, com os campos separados por `|`. A resposta começa com `OK` ou `ERRO|motivo`.

| Comando | Cliente envia | Servidor responde |
| --- | --- | --- |
| LOGIN | `LOGIN\|usuario\|senha` | `OK\|mensagem` ou `ERRO\|senha incorreta` |
| UPLOAD | `UPLOAD\|praia.jpg\|48213` | `OK\|pode enviar`, depois recebe o arquivo |
| (fim do upload) | `FIM` | `OK\|<sha256>` ou `ERRO\|motivo` |
| LIST | `LIST` | `OK\|<tamanho>\|lista\|<sha256>`, depois manda a lista |
| DOWNLOAD | `DOWNLOAD\|<id ou nome>` | `OK\|<tamanho>\|<nome>\|<sha256>`, depois manda a imagem |
| VIEW | `VIEW\|<id ou nome>` | `OK\|<tamanho>\|<id>.jpg\|<sha256>`, depois manda a miniatura |
| HIST | `HIST` | `OK\|<tamanho>\|historico\|<sha256>`, depois manda o histórico |

Quando o servidor vai mandar algo (LIST, DOWNLOAD, VIEW, HIST), o cliente responde `PRONTO` antes, para avisar que está esperando os dados.

Cada linha do LIST: `id | nome | autor | data | tamanho`. Cada linha do HIST: `data | usuario | acao | id`.


## COMO A TRANSFERÊNCIA FUNCIONA (transfer.py)

Uma imagem não cabe num datagrama, então ela é dividida em pedaços de 1400 bytes e mandada com stop-and-wait:

1. Cada pedaço vai num pacote `FRM` + número do pedaço (4 bytes) + tamanho (4 bytes) + dados.
2. O receptor responde `ACK` + número do pedaço. Pedaço repetido é descartado, mas o ACK é mandado de novo (o primeiro ACK pode ter se perdido).
3. Se o ACK não chega em 0,5 s, o pedaço é reenviado (até 20 vezes).
4. No fim vai `EOF` + sha256 do arquivo inteiro. O receptor junta os pedaços em ordem, calcula o sha256 e responde `OKF` se bateu ou `ERR` se não bateu.

Além disso:

* Os comandos também podem se perder, então o cliente reenvia o comando se não tiver resposta em 0,1 s (até 20 vezes). O servidor reconhece o comando repetido e só reenvia a resposta, sem executar de novo (para não fazer o mesmo upload duas vezes, por exemplo).
* O servidor tem um socket principal na porta 5000 só para receber comandos. Cada pedido roda numa thread e, quando tem arquivo, abre um socket próprio numa porta livre para a transferência. Assim um upload grande não mistura os pacotes com os comandos dos outros clientes.
* O cliente confere o sha256 do que recebeu com o que o servidor mandou na resposta, e no upload confere o sha256 que o servidor devolve com o do arquivo enviado.


## ONDE FICAM OS ARQUIVOS

| Arquivo ou pasta | O que tem |
| --- | --- |
| `uploads/<usuario>/<id>.<extensao>` | Imagem original |
| `thumbnails/<usuario>/<id>.jpg` | Miniatura JPEG de até 128x128 (mantém a proporção) |
| `repository.db` | Banco SQLite com as tabelas `usuarios`, `imagens` e `historico` |
| `downloads/` (lado do cliente) | Imagens e miniaturas baixadas |

O id da imagem são os 12 primeiros caracteres do sha256 do conteúdo. Por isso duas imagens com o mesmo nome não se sobrescrevem, e a mesma imagem enviada duas vezes é recusada. A senha é guardada como sha256, nunca em texto.

Para começar do zero, é só apagar o `repository.db` e as pastas criadas dentro de `uploads/` e `thumbnails/`.


## RESPONSABILIDADE DE CADA ARQUIVO

| Arquivo | Responsabilidade |
| --- | --- |
| `server.py` | Servidor UDP: recebe os comandos, uma thread por pedido |
| `client.py` | Menu do terminal, monta os comandos e salva os downloads |
| `protocol.py` | Formato das mensagens de texto e dos tipos de pacote |
| `transfer.py` | Envio e recebimento confiável: pedaços, ACK, timeout, retransmissão e hash |
| `storage.py` | Validar, salvar e ler imagens e miniaturas (da APS 01) |
| `database.py` | Usuários, imagens e histórico no SQLite (da APS 01) |


## LIMITAÇÕES

* Stop-and-wait manda um pedaço por vez. Na rede local é rápido, mas com perda de pacotes cada perda custa 0,5 s de espera, então arquivos grandes demoram.
* O limite é 10 MB por imagem.
* Senha em sha256 sem salt. Numa aplicação real seria bcrypt ou parecido.
* O login fica preso ao endereço (ip, porta) do cliente: fechou o cliente, tem que logar de novo.
