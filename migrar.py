"""Aplica as migrações de migracoes/*.sql que ainda não rodaram neste banco.

Roda sozinho quando o gunicorn sobe (veja gunicorn.conf.py) e também pode ser
chamado à mão:  python migrar.py

- Cada arquivo aplicado fica registrado na tabela schema_migracoes.
- Um lock do MySQL (GET_LOCK) impede que dois processos migrem ao mesmo tempo.
- Banco criado com o schema.sql atual (já tem clientes.versao): as migrações
  existentes são só registradas, sem rodar de novo.
- Se uma migração falha (ex.: CPFs repetidos), o erro sobe e o servidor não
  inicia; no Render, a versão anterior continua no ar.
"""

import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

PASTA = Path(__file__).resolve().parent / "migracoes"
LOCK = "sistema_clientes_migracoes"


def conectar():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", "3306")),
        connection_timeout=10,
    )


def comandos(arquivo):
    texto = arquivo.read_text(encoding="utf-8")
    sem_comentarios = "\n".join(
        linha for linha in texto.splitlines() if not linha.strip().startswith("--")
    )
    return [c.strip() for c in sem_comentarios.split(";") if c.strip()]


def _existe_coluna(cursor, tabela, coluna):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.columns"
        " WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (tabela, coluna),
    )
    return cursor.fetchone()[0] > 0


def migrar(log=print):
    """Aplica as pendentes e devolve a lista de arquivos aplicados."""

    arquivos = sorted(PASTA.glob("*.sql"))
    db = conectar()
    db.autocommit = True
    cursor = db.cursor()
    try:
        cursor.execute("SELECT GET_LOCK(%s, 120)", (LOCK,))
        if cursor.fetchone()[0] != 1:
            raise RuntimeError("não consegui o lock de migração em 120 s")

        cursor.execute(
            "CREATE TABLE IF NOT EXISTS schema_migracoes ("
            " nome VARCHAR(255) NOT NULL PRIMARY KEY,"
            " aplicada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        cursor.execute("SELECT nome FROM schema_migracoes")
        feitas = {linha[0] for linha in cursor.fetchall()}

        if not feitas and _existe_coluna(cursor, "clientes", "versao"):
            # Banco já nasceu com o schema.sql atual: nada a migrar.
            for arquivo in arquivos:
                cursor.execute("INSERT INTO schema_migracoes (nome) VALUES (%s)", (arquivo.name,))
            log(f"migrações: schema atual, {len(arquivos)} registradas sem aplicar")
            return []

        aplicadas = []
        for arquivo in arquivos:
            if arquivo.name in feitas:
                continue
            log(f"migrações: aplicando {arquivo.name}")
            for comando in comandos(arquivo):
                cursor.execute(comando)
            cursor.execute("INSERT INTO schema_migracoes (nome) VALUES (%s)", (arquivo.name,))
            aplicadas.append(arquivo.name)
        log(f"migrações: {len(aplicadas)} aplicadas" if aplicadas else "migrações: nada pendente")
        return aplicadas
    finally:
        try:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK,))
            cursor.fetchall()
        finally:
            cursor.close()
            db.close()


if __name__ == "__main__":
    load_dotenv(override=True)
    try:
        migrar()
    except mysql.connector.Error as erro:
        sys.exit(f"migrações: falhou: {erro}")
