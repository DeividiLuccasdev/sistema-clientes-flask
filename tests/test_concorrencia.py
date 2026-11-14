"""Cenários de concorrência e idempotência contra o MySQL real.

Cada requisição paralela usa seu próprio test client (sessão e conexão
próprias), e uma threading.Barrier solta todas ao mesmo tempo.
"""

import hashlib
import threading

import mysql.connector
import pytest

import app as modulo
from tests.conftest import SENHA, Cliente, consultar_um, criar_cliente, executar_sql, novo_logado
from tests.test_app import dados_cliente


def em_paralelo(funcoes):
    barreira = threading.Barrier(len(funcoes))
    resultados = [None] * len(funcoes)
    erros = []

    def rodar(indice, funcao):
        barreira.wait()
        try:
            resultados[indice] = funcao()
        except BaseException as erro:  # noqa: BLE001 - repassado ao teste
            erros.append(erro)

    threads = [
        threading.Thread(target=rodar, args=(indice, funcao))
        for indice, funcao in enumerate(funcoes)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    # Uma exceção aqui seria um 500 em produção
    assert not erros, erros
    return resultados


def contar(sql, parametros=None):
    return consultar_um(sql, parametros)["total"]


# CPF único

def test_cadastros_simultaneos_com_mesmo_cpf(usuario):
    navegadores = [novo_logado() for _ in range(10)]
    # Metade com máscara, metade só dígitos: é o mesmo CPF
    cpfs = ["123.456.789-09", "12345678909"] * 5

    respostas = em_paralelo([
        (lambda n=n, cpf=cpf: n.post("/novo", data=dados_cliente(nome="Ana", cpf=cpf)))
        for n, cpf in zip(navegadores, cpfs)
    ])

    status = sorted(r.status_code for r in respostas)
    assert status == [200] * 9 + [302]
    for resposta in respostas:
        if resposta.status_code == 200:
            assert "Já existe um cliente cadastrado com esse CPF" in resposta.get_data(as_text=True)

    assert contar("SELECT COUNT(*) AS total FROM clientes") == 1


def test_schema_recusa_cpf_duplicado_com_outra_formatacao():
    criar_cliente(cpf="111.111.111-11")

    with pytest.raises(mysql.connector.IntegrityError) as erro:
        criar_cliente(nome="Outro", cpf="11111111111")

    assert erro.value.errno == 1062


def test_cliente_sem_cpf_nao_conflita():
    criar_cliente(nome="A", cpf="")
    criar_cliente(nome="B", cpf="")

    assert contar("SELECT COUNT(*) AS total FROM clientes") == 2


# Exclusão

def test_exclusoes_simultaneas_gravam_um_historico(usuario):
    cliente_id = criar_cliente(nome="João")
    navegadores = [novo_logado() for _ in range(2)]

    respostas = em_paralelo([
        (lambda n=n: n.post(f"/excluir/{cliente_id}")) for n in navegadores
    ])

    assert [r.status_code for r in respostas] == [302, 302]
    assert consultar_um("SELECT id FROM clientes WHERE id = %s", (cliente_id,)) is None
    assert contar("SELECT COUNT(*) AS total FROM historico_exclusoes") == 1


# Edição (trava otimista)

def test_edicao_com_versao_antiga_nao_sobrescreve(usuario):
    cliente_id = criar_cliente(nome="Maria")
    primeira, segunda = novo_logado(), novo_logado()

    # As duas abriram o formulário na versão 0
    assert 'name="versao" value="0"' in primeira.get(f"/editar/{cliente_id}").get_data(as_text=True)

    ok = primeira.post(f"/editar/{cliente_id}", data=dados_cliente(nome="Maria Silva"))
    atrasada = segunda.post(f"/editar/{cliente_id}", data=dados_cliente(nome="Maria Souza"))

    assert ok.status_code == 302
    assert atrasada.status_code == 409
    pagina = atrasada.get_data(as_text=True)
    assert "alterado por outra pessoa" in pagina
    # O formulário volta com os dados atuais e a nova versão
    assert 'value="Maria Silva"' in pagina
    assert 'name="versao" value="1"' in pagina

    salvo = consultar_um("SELECT nome, versao FROM clientes WHERE id = %s", (cliente_id,))
    assert salvo == {"nome": "Maria Silva", "versao": 1}


def test_edicoes_simultaneas_so_uma_grava(usuario):
    cliente_id = criar_cliente(nome="Maria")
    navegadores = [novo_logado() for _ in range(2)]
    nomes = ["Maria A", "Maria B"]

    respostas = em_paralelo([
        (lambda n=n, nome=nome: n.post(f"/editar/{cliente_id}", data=dados_cliente(nome=nome)))
        for n, nome in zip(navegadores, nomes)
    ])

    assert sorted(r.status_code for r in respostas) == [302, 409]
    vencedor = nomes[[r.status_code for r in respostas].index(302)]
    salvo = consultar_um("SELECT nome, versao FROM clientes WHERE id = %s", (cliente_id,))
    assert salvo == {"nome": vencedor, "versao": 1}


def test_edicao_de_cliente_excluido_retorna_404(logado):
    cliente_id = criar_cliente()
    executar_sql("DELETE FROM clientes WHERE id = %s", (cliente_id,))

    resposta = logado.post(f"/editar/{cliente_id}", data=dados_cliente(nome="Fantasma"))

    assert resposta.status_code == 404
    assert contar("SELECT COUNT(*) AS total FROM clientes") == 0


def test_edicao_sem_versao_e_tratada_como_conflito(logado):
    cliente_id = criar_cliente(nome="Maria")
    dados = dados_cliente(nome="Outro nome")
    del dados["versao"]

    assert logado.post(f"/editar/{cliente_id}", data=dados).status_code == 409
    assert consultar_um("SELECT nome FROM clientes WHERE id = %s", (cliente_id,))["nome"] == "Maria"


# Limite de tentativas

def test_logins_simultaneos_respeitam_o_limite(usuario):
    navegadores = [Cliente() for _ in range(20)]

    respostas = em_paralelo([
        (lambda n=n: n.post("/login", data={"usuario": "admin", "senha": "errada"}))
        for n in navegadores
    ])

    liberadas = [r for r in respostas if r.status_code != 429]
    assert len(liberadas) == modulo.LIMITE_TENTATIVAS
    # Nem a senha certa entra enquanto o bloqueio durar
    assert Cliente().post("/login", data={"usuario": "admin", "senha": SENHA}).status_code == 429


def test_login_com_sucesso_zera_o_contador(client, usuario):
    for _ in range(modulo.LIMITE_TENTATIVAS - 1):
        client.post("/login", data={"usuario": "admin", "senha": "errada"})

    assert client.post("/login", data={"usuario": "admin", "senha": SENHA}).status_code == 302
    assert contar("SELECT COUNT(*) AS total FROM tentativas_acesso") == 0


def test_recuperacoes_simultaneas_respeitam_o_limite(usuario, monkeypatch):
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: None)
    navegadores = [Cliente() for _ in range(10)]

    respostas = em_paralelo([
        (lambda n=n: n.post("/esqueci-senha", data={"email": "nao@existe.com"}))
        for n in navegadores
    ])

    assert sum(r.status_code != 429 for r in respostas) == modulo.LIMITE_TENTATIVAS


# Recuperação de senha

def test_token_de_recuperacao_e_consumido_uma_vez(usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: enviados.append(link))
    Cliente().post("/esqueci-senha", data={"email": usuario["email"]})
    caminho = enviados[0].replace("https://clientes.exemplo.com", "")
    token = caminho.rsplit("/", 1)[1]

    # O banco guarda só o hash do token
    gravado = consultar_um("SELECT token_recuperacao FROM usuarios WHERE usuario = 'admin'")
    assert gravado["token_recuperacao"] == hashlib.sha256(token.encode()).hexdigest()

    senhas = ["primeira1", "segunda22"]
    respostas = em_paralelo([
        (lambda n=Cliente(), s=s: n.post(caminho, data={"senha": s, "confirmar_senha": s}))
        for s in senhas
    ])

    assert sorted(r.status_code for r in respostas) == [302, 400]
    vencedora = senhas[[r.status_code for r in respostas].index(302)]
    perdedora = senhas[1 - senhas.index(vencedora)]

    assert Cliente().post("/login", data={"usuario": "admin", "senha": vencedora}).status_code == 302
    assert Cliente().post("/login", data={"usuario": "admin", "senha": perdedora}).status_code == 200

    reuso = Cliente().post(caminho, data={"senha": "terceira3", "confirmar_senha": "terceira3"})
    assert reuso.status_code == 400


# Duplo envio do cadastro de usuário

def test_novo_usuario_redireciona_depois_de_salvar(logado):
    resposta = logado.post("/novo-usuario", data={
        "nome": "Bia", "usuario": "bia", "email": "bia@exemplo.com", "senha": "segredo123",
    })

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/novo-usuario")
    assert "Usuário cadastrado com sucesso" in logado.get("/novo-usuario").get_data(as_text=True)
    # Recarregar a página (GET) não cadastra de novo nem repete a mensagem
    assert "Usuário cadastrado com sucesso" not in logado.get("/novo-usuario").get_data(as_text=True)
    assert contar("SELECT COUNT(*) AS total FROM usuarios WHERE usuario = 'bia'") == 1
