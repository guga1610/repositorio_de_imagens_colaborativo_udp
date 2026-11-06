Sistema distribuído cliente-servidor com Sockets UDP para compartilhamento colaborativo de imagens. Permite upload, armazenamento, listagem, visualização por miniaturas e download, mantendo um histórico com informações sobre autoria, data de envio e tamanho dos arquivos.

APS 02: mesma atividade da APS 01, agora usando UDP. Como o UDP não garante entrega, ordem nem ausência de duplicatas, a confiabilidade é feita na aplicação.


## TECNOLOGIAS A SEREM USADAS:

* socket (SOCK_DGRAM): comunicacao UDP
* threading: atender mais de um cliente ao mesmo tempo
* os: Gerenciamento de arquivos e diretórios
* hashlib: id das imagens e hash das senhas
* Pillow: geração de miniatura
* sqlite3: banco de dados


COMANDOS DO SISTEMA:

| Comando    | Função                     | Resposta esperada            |
| ---------- | -------------------------- | ---------------------------- |
| `LOGIN`    | Identificar o usuário (opcional) | Confirmação ou erro    |
| `UPLOAD`   | Enviar uma imagem          | Confirmação do armazenamento |
| `LIST`     | Listar imagens disponíveis | Lista de metadados           |
| `DOWNLOAD` | Baixar uma imagem original | Tamanho e bytes da imagem    |
| `VIEW`     | Obter uma miniatura        | Tamanho e bytes da miniatura |


DIFERENÇAS PARA A VERSÃO TCP:

* Não tem conexão: o servidor usa um socket só e identifica cada cliente pelo endereço (ip, porta) que vem no `recvfrom`
* Uma imagem não cabe em um datagrama, então ela vai ser dividida em pedaços numerados
* Cada pedaço precisa de confirmação (ACK). Se o ACK não chegar dentro do timeout, o pedaço é reenviado
* O receptor descarta pedaços repetidos e remonta a imagem na ordem certa


RESPONSABILIDADE DE CADA ARQUIVO:

| Arquivo ou diretório | Responsabilidade                         |
| -------------------- | ---------------------------------------- |
| `server.py`          | Criar o servidor UDP e atender clientes  |
| `client.py`          | Enviar comandos e receber as respostas   |
| `protocol.py`        | Definir o formato das mensagens e dos pacotes |
| `transfer.py`        | Envio e recebimento confiável (pedaços, ACK, timeout, retransmissão) |
| `storage.py`         | Salvar, localizar e recuperar imagens (da APS 01) |
| `database.py`        | Registrar usuários, arquivos e histórico (da APS 01) |
| `uploads/`           | Armazenar as imagens originais           |
| `thumbnails/`        | Armazenar as miniaturas                  |
| `repository.db`      | Metadados no SQLite (criado pelo servidor) |
| `README.md`          | Documentar a instalação e a utilização   |


## COMO RODAR

(a fazer)

Por enquanto, para testar a comunicação: `python server.py` em um terminal e `python client.py` em outro.
