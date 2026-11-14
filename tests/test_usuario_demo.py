"""Conta de demonstração: seed no deploy e proteções contra visitantes."""

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import app as modulo
from tests.conftest import Cliente, conectar, consultar_um, executar_sql
from usuario_demo import (
    DEMO_EMAIL,
    DEMO_NOME,
    DEMO_SENHA,
    DEMO_USUARIO,
    eh_usuario_demo,
    garantir_usuario_demo,
)


@pytest.fixture
def sem_variaveis(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("CRIAR_USUARIO_DEMO", raising=False)


@pytest.fixture
def com_seed(sem_variaveis, monkeypatch):
    monkeypatch.setenv("CRIAR_USUARIO_DEMO", "true")


def semear():
    return garantir_usuario_demo(log=lambda _msg: None, conectar=conectar)


def contar_demo():
    return consultar_um(
        "SELECT COUNT(*) AS n FROM usuarios WHERE usuario = %s", (DEMO_USUARIO,)
    )["n"]


@pytest.fixture
def demo_logado(com_seed):
    semear()
    cliente = Cliente()
    resposta = cliente.post("/login", data={"usuario": DEMO_USUARIO, "senha": DEMO_SENHA})
    assert resposta.status_code == 302
    return cliente


# Seed

def test_seed_nao_faz_nada_sem_a_variavel(sem_variaveis):
    assert semear() is False
    assert contar_demo() == 0


def test_seed_roda_no_render(sem_variaveis, monkeypatch):
    monkeypatch.setenv("RENDER", "true")

    assert semear() is True
    assert contar_demo() == 1


def test_seed_cria_e_e_idempotente(com_seed, client):
    assert semear() is True
    assert semear() is True

    assert contar_demo() == 1
    demo = consultar_um("SELECT nome, email, ativo FROM usuarios WHERE usuario = %s", (DEMO_USUARIO,))
    assert demo == {"nome": DEMO_NOME, "email": DEMO_EMAIL, "ativo": 1}
    assert client.post("/login", data={"usuario": DEMO_USUARIO, "senha": DEMO_SENHA}).status_code == 302


def test_seed_restaura_demo_alterada(com_seed, client):
    semear()
    executar_sql(
        "UPDATE usuarios SET senha = %s, ativo = FALSE, token_recuperacao = %s,"
        " token_expiracao = NOW() + INTERVAL 30 MINUTE WHERE usuario = %s",
        (generate_password_hash("vandalizada1"), "a" * 64, DEMO_USUARIO),
    )
    assert client.post("/login", data={"usuario": DEMO_USUARIO, "senha": DEMO_SENHA}).status_code == 200

    semear()

    demo = consultar_um(
        "SELECT senha, ativo, token_recuperacao FROM usuarios WHERE usuario = %s", (DEMO_USUARIO,)
    )
    assert demo["ativo"] == 1
    assert demo["token_recuperacao"] is None
    assert check_password_hash(demo["senha"], DEMO_SENHA)
    assert contar_demo() == 1
    assert client.post("/login", data={"usuario": DEMO_USUARIO, "senha": DEMO_SENHA}).status_code == 302


# Proteções

def test_helper_reconhece_usuario_e_email():
    assert eh_usuario_demo("demo")
    assert eh_usuario_demo(" DEMO ")
    assert eh_usuario_demo(email="Demo@Example.com")
    assert not eh_usuario_demo("admin", "admin@exemplo.com")
    assert not eh_usuario_demo(None, None)


def test_recuperacao_ignora_demo_em_silencio(demo_logado, monkeypatch):
    enviados = []
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: enviados.append(link))
    cliente = Cliente()

    demo = cliente.post("/esqueci-senha", data={"email": DEMO_EMAIL})
    inexistente = cliente.post("/esqueci-senha", data={"email": "nao@existe.com"})

    assert demo.status_code == inexistente.status_code == 200
    assert demo.get_data(as_text=True) == inexistente.get_data(as_text=True)
    assert enviados == []
    token = consultar_um("SELECT token_recuperacao FROM usuarios WHERE usuario = %s", (DEMO_USUARIO,))
    assert token["token_recuperacao"] is None


def test_link_de_redefinicao_da_demo_e_recusado(demo_logado):
    # Mesmo com um token válido gravado (ex.: de antes desta proteção)
    token = "token-da-demo"
    executar_sql(
        "UPDATE usuarios SET token_recuperacao = %s, token_expiracao = NOW() + INTERVAL 30 MINUTE"
        " WHERE usuario = %s",
        (modulo.hash_token(token), DEMO_USUARIO),
    )
    cliente = Cliente()

    assert cliente.get(f"/redefinir-senha/{token}").status_code == 403
    resposta = cliente.post(
        f"/redefinir-senha/{token}", data={"senha": "trocada123", "confirmar_senha": "trocada123"}
    )

    assert resposta.status_code == 403
    assert "conta de demonstração" in resposta.get_data(as_text=True)
    assert cliente.post("/login", data={"usuario": DEMO_USUARIO, "senha": DEMO_SENHA}).status_code == 302


# "login" e não "usuario": o nome não pode coincidir com a fixture usuario
@pytest.mark.parametrize("login, email", [
    ("demo", "outro@exemplo.com"),
    ("Demo", "outro@exemplo.com"),
    ("outro", "DEMO@example.com"),
])
def test_ninguem_registra_usuario_ou_email_da_demo(logado, login, email):
    resposta = logado.post("/novo-usuario", data={
        "nome": "Intruso", "usuario": login, "email": email, "senha": "senha12345",
    })

    assert "reservado para a conta de demonstração" in resposta.get_data(as_text=True)
    assert consultar_um("SELECT id FROM usuarios WHERE nome = 'Intruso'") is None


def test_demo_logada_usa_o_sistema(demo_logado):
    assert demo_logado.get("/").status_code == 200
