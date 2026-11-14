-- Migração para bancos criados com o schema.sql anterior (MySQL 8).
-- Uso: mysql -u root -p sistema_clientes < migracoes/001_concorrencia_idempotencia.sql
--
-- Antes de rodar, veja se já existem CPFs repetidos (com ou sem máscara):
--
--   SELECT REGEXP_REPLACE(cpf, '[^0-9]', '') AS cpf_digitos,
--          COUNT(*) AS quantidade,
--          GROUP_CONCAT(id ORDER BY id) AS ids
--   FROM clientes
--   WHERE NULLIF(REGEXP_REPLACE(cpf, '[^0-9]', ''), '') IS NOT NULL
--   GROUP BY cpf_digitos
--   HAVING COUNT(*) > 1;
--
-- Se a consulta retornar linhas, decida qual cadastro manter e exclua ou
-- corrija os outros. Com duplicados, o passo 1 falha com o erro 1062
-- (Duplicate entry) e nada desta etapa é aplicado: nenhum dado é apagado
-- automaticamente.

-- 1. CPF normalizado e único
ALTER TABLE clientes
    ADD COLUMN cpf_digitos VARCHAR(14) GENERATED ALWAYS AS (
        NULLIF(REGEXP_REPLACE(cpf, '[^0-9]', ''), '')
    ) STORED AFTER cpf,
    ADD UNIQUE KEY uq_clientes_cpf_digitos (cpf_digitos);

-- 2. Versão para a trava otimista da edição
ALTER TABLE clientes
    ADD COLUMN versao INT NOT NULL DEFAULT 0;

-- 3. Token de recuperação passa a ser guardado como hash SHA-256.
--    Links já enviados (com o token em texto puro) deixam de valer.
UPDATE usuarios SET token_recuperacao = NULL, token_expiracao = NULL;

ALTER TABLE usuarios
    MODIFY token_recuperacao CHAR(64) NULL,
    ADD UNIQUE KEY uq_usuarios_token_recuperacao (token_recuperacao);

-- 4. Limite de tentativas compartilhado entre processos
CREATE TABLE IF NOT EXISTS tentativas_acesso (
    chave VARCHAR(255) NOT NULL PRIMARY KEY,
    tentativas INT NOT NULL,
    janela_inicio DATETIME NOT NULL
);
