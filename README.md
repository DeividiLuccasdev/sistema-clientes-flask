# Sistema de Clientes

Sistema web desenvolvido para gerenciamento de clientes, permitindo cadastrar, pesquisar, editar e excluir registros.

Este projeto foi desenvolvido como parte dos meus estudos de desenvolvimento web com Python, Flask e MySQL.
## 📸 Tela do Sistema

![Sistema de Clientes](screenshots/sistema-clientes.png)

## 🚀 Funcionalidades

- Cadastro de clientes
- Edição de clientes
- Exclusão com confirmação
- Pesquisa de clientes
- Sugestões de nomes durante a pesquisa
- Validação de CPF duplicado
- Máscaras para CPF, telefone e data de nascimento
- Registro da data de cadastro
- Registro de atualizações
- Histórico de exclusões
- Dashboard com indicadores:
  - Total de clientes
  - Novos clientes
  - Clientes atualizados
  - Clientes removidos

## 🛠️ Tecnologias utilizadas

- Python
- Flask
- MySQL
- HTML
- CSS
- JavaScript
- Git
- GitHub

## 📂 Estrutura do projeto

Sistema_Clientes/
├── app.py
├── requirements.txt
├── templates/
│   ├── index.html
│   ├── novo_cliente.html
│   └── editar_cliente.html
└── static/
    └── css/
        └── style.css

## 🔐 Segurança

As credenciais do banco de dados são armazenadas em variáveis de ambiente utilizando um arquivo `.env`.

O arquivo `.env` não é enviado ao GitHub.

## ▶️ Como executar

Instale as dependências:

pip install -r requirements.txt

Crie um arquivo `.env` com as configurações do seu banco MySQL.

Depois execute:

python app.py

Acesse no navegador:

http://127.0.0.1:5000
## 🗄️ Configuração do banco de dados

Crie o banco de dados:

```sql
CREATE DATABASE sistema_clientes;
USE sistema_clientes;
CREATE TABLE clientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    telefone VARCHAR(20),
    email VARCHAR(100),
    cpf VARCHAR(14),
    cidade VARCHAR(100),
    data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao DATETIME NULL,
    data_nascimento DATE NULL
);
CREATE TABLE historico_exclusoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT,
    nome VARCHAR(100),
    data_exclusao DATETIME DEFAULT CURRENT_TIMESTAMP
);
Crie um arquivo `.env` na raiz do projeto:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=sua_senha_aqui
DB_NAME=sistema_clientes
```
## 👨‍💻 Autor

Desenvolvido por Deividi Luccas.