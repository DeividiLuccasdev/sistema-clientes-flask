"""Aplica migracoes/001 sobre o schema anterior a esta versão."""

import mysql.connector
import pytest

from tests.conftest import RAIZ, conectar, consultar_um, executar_sql

SCHEMA_ANTIGO = [
    "DROP TABLE IF EXISTS tentativas_acesso",
    "DROP TABLE IF EXISTS clientes",
    "DROP TABLE IF EXISTS usuarios",
    """
    CREATE TABLE usuarios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(100) NOT NULL,
        usuario VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(150) NOT NULL UNIQUE,
        senha VARCHAR(255) NOT NULL,
        ativo BOOLEAN NOT NULL DEFAULT TRUE,
        token_recuperacao VARCHAR(100) NULL,
        token_expiracao DATETIME NULL
    )
    """,
    """
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
    )
    """,
]


def executar_varios(comandos):
    db = conectar()
    cursor = db.cursor()
    try:
        for comando in comandos:
            cursor.execute(comando)
        db.commit()
    finally:
        cursor.close()
        db.close()


def comandos_da_migracao():
    texto = (RAIZ / "migracoes" / "001_concorrencia_idempotencia.sql").read_text(encoding="utf-8")
    sem_comentarios = "\n".join(
        linha for linha in texto.splitlines() if not linha.strip().startswith("--")
    )
    return [c for c in sem_comentarios.split(";") if c.strip()]


def preparar_banco_antigo(cpfs):
    executar_varios(SCHEMA_ANTIGO)
    for indice, cpf in enumerate(cpfs):
        executar_sql("INSERT INTO clientes (nome, cpf) VALUES (%s, %s)", (f"C{indice}", cpf))
    executar_sql(
        "INSERT INTO usuarios (nome, usuario, email, senha, token_recuperacao, token_expiracao)"
        " VALUES ('A', 'a', 'a@x.com', 'h', 'token-antigo-em-texto', NOW() + INTERVAL 1 HOUR)"
    )


def test_migracao_aplica_em_banco_sem_duplicados():
    preparar_banco_antigo(["111.111.111-11", "22222222222", ""])

    executar_varios(comandos_da_migracao())

    assert consultar_um("SELECT cpf_digitos, versao FROM clientes WHERE nome = 'C0'") == {
        "cpf_digitos": "11111111111",
        "versao": 0,
    }
    # Links antigos (token em texto puro) são invalidados
    assert consultar_um("SELECT token_recuperacao FROM usuarios")["token_recuperacao"] is None
    with pytest.raises(mysql.connector.IntegrityError):
        executar_sql("INSERT INTO clientes (nome, cpf) VALUES ('X', '111.111.111-11')")
    assert consultar_um("SELECT COUNT(*) AS total FROM tentativas_acesso")["total"] == 0


def test_migracao_falha_sem_apagar_nada_quando_ha_cpf_repetido():
    preparar_banco_antigo(["111.111.111-11", "11111111111"])

    with pytest.raises(mysql.connector.IntegrityError) as erro:
        executar_varios(comandos_da_migracao())

    assert erro.value.errno == 1062
    assert consultar_um("SELECT COUNT(*) AS total FROM clientes")["total"] == 2
