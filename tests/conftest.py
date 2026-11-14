import os
import secrets
import sys
from pathlib import Path

import mysql.connector
import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Configuração para os testes (antes de importar a aplicação).
# O banco vem das variáveis DB_*; por padrão, um MySQL local na porta 3306.
os.environ.setdefault("SECRET_KEY", "chave-de-teste-com-pelo-menos-32-caracteres")
os.environ.setdefault("APP_URL", "https://clientes.exemplo.com")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_USER", "root")
os.environ.setdefault("DB_PASSWORD", "root")
os.environ.setdefault("DB_NAME", "sistema_clientes_teste")
os.environ["SESSION_COOKIE_SECURE"] = "false"

sys.path.insert(0, str(RAIZ))

import app as modulo  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

SENHA = "senha12345"


def conectar():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )


def executar_sql(sql, parametros=None):
    db = conectar()
    cursor = db.cursor()
    try:
        cursor.execute(sql, parametros or ())
        db.commit()
        return cursor.lastrowid
    finally:
        # Sem isso, um INSERT recusado (ex.: CPF duplicado) deixava a transação
        # aberta segurando o lock da tabela e o DROP do próximo teste travava.
        cursor.close()
        db.close()


def consultar_um(sql, parametros=None):
    db = conectar()
    cursor = db.cursor(dictionary=True)
    cursor.execute(sql, parametros or ())
    linha = cursor.fetchone()
    cursor.close()
    db.close()
    return linha


@pytest.fixture(autouse=True)
def banco_limpo():
    """Recria as tabelas a partir do schema.sql (inclusive os limites de tentativas)."""

    db = conectar()
    cursor = db.cursor()
    # Uma conexão esquecida com transação aberta faz o DROP falhar em vez de travar
    cursor.execute("SET SESSION lock_wait_timeout = 30")

    for tabela in ("tentativas_acesso", "historico_exclusoes", "clientes", "usuarios"):
        cursor.execute(f"DROP TABLE IF EXISTS {tabela}")

    for comando in (RAIZ / "schema.sql").read_text(encoding="utf-8").split(";"):
        linhas = [l for l in comando.splitlines() if not l.strip().startswith("--")]
        if "\n".join(linhas).strip():
            cursor.execute("\n".join(linhas))

    db.commit()
    cursor.close()
    db.close()

    yield


class Cliente:
    """Test client que envia o token CSRF da sessão em todo POST."""

    def __init__(self):
        modulo.app.config["TESTING"] = True
        self.http = modulo.app.test_client()

    def token(self):
        with self.http.session_transaction() as sessao:
            if "_csrf_token" not in sessao:
                sessao["_csrf_token"] = secrets.token_urlsafe(32)
            return sessao["_csrf_token"]

    def get(self, url, **kwargs):
        return self.http.get(url, **kwargs)

    def post(self, url, data=None, **kwargs):
        dados = dict(data or {})
        dados["_csrf_token"] = self.token()
        return self.http.post(url, data=dados, **kwargs)


@pytest.fixture
def client():
    return Cliente()


@pytest.fixture
def usuario():
    executar_sql(
        "INSERT INTO usuarios (nome, usuario, email, senha) VALUES (%s, %s, %s, %s)",
        ("Admin", "admin", "admin@exemplo.com", generate_password_hash(SENHA)),
    )
    return {"usuario": "admin", "email": "admin@exemplo.com"}


def novo_logado():
    """Outro navegador já autenticado (cada um com sua sessão e conexão)."""

    cliente = Cliente()
    resposta = cliente.post("/login", data={"usuario": "admin", "senha": SENHA})
    assert resposta.status_code == 302
    return cliente


@pytest.fixture
def logado(client, usuario):
    resposta = client.post("/login", data={"usuario": "admin", "senha": SENHA})
    assert resposta.status_code == 302
    return client


def criar_cliente(nome="Maria", cpf="111.111.111-11"):
    return executar_sql(
        "INSERT INTO clientes (nome, cpf, data_nascimento) VALUES (%s, %s, '1990-01-01')",
        (nome, cpf),
    )
