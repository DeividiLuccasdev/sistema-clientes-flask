-- Estrutura do banco do Sistema de Clientes (MySQL 8)
-- Uso: mysql -u root -p sistema_clientes < schema.sql
-- Bancos criados antes desta versão: aplique migracoes/001_concorrencia_idempotencia.sql

CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    usuario VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(150) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    -- SHA-256 (hex) do token enviado por e-mail: o token em si nunca é gravado
    token_recuperacao CHAR(64) NULL UNIQUE,
    token_expiracao DATETIME NULL
);

CREATE TABLE IF NOT EXISTS clientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    telefone VARCHAR(20),
    email VARCHAR(100),
    cpf VARCHAR(14),
    -- Só os dígitos do CPF: "111.111.111-11" e "11111111111" são o mesmo cliente.
    -- O UNIQUE é o que impede duplicidade mesmo com cadastros simultâneos.
    cpf_digitos VARCHAR(14) GENERATED ALWAYS AS (
        NULLIF(REGEXP_REPLACE(cpf, '[^0-9]', ''), '')
    ) STORED,
    cidade VARCHAR(100),
    data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao DATETIME NULL,
    data_nascimento DATE NULL,
    -- Controle de concorrência otimista: cada UPDATE incrementa a versão
    versao INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_clientes_cpf_digitos (cpf_digitos)
);

CREATE TABLE IF NOT EXISTS historico_exclusoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT,
    nome VARCHAR(100),
    data_exclusao DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Limite de tentativas (login e recuperação de senha) compartilhado entre
-- processos e workers. A contagem é feita com um único upsert atômico.
CREATE TABLE IF NOT EXISTS tentativas_acesso (
    chave VARCHAR(255) NOT NULL PRIMARY KEY,
    tentativas INT NOT NULL,
    janela_inicio DATETIME NOT NULL
);
