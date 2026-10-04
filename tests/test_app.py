import app as modulo
from tests.conftest import SENHA, consultar_um, criar_cliente


def dados_cliente(**extra):
    dados = {
        "nome": "Maria", "telefone": "", "email": "", "cpf": "111.111.111-11",
        "cidade": "", "data_nascimento": "01/01/1990",
    }
    dados.update(extra)
    return dados


# Login e sessão

def test_paginas_exigem_login(client):
    for url in ("/", "/novo", "/novo-usuario", "/editar/1"):
        resposta = client.get(url)
        assert resposta.status_code == 302
        assert resposta.headers["Location"].endswith("/login")


def test_login_e_senha_errada(client, usuario):
    assert client.post("/login", data={"usuario": "admin", "senha": "errada"}).status_code == 200
    assert client.post("/login", data={"usuario": "admin", "senha": SENHA}).status_code == 302


def test_cookie_de_sessao_protegido(client, usuario):
    resposta = client.post("/login", data={"usuario": "admin", "senha": SENHA})
    cookie = resposta.headers["Set-Cookie"]

    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_post_sem_token_csrf_e_recusado(logado):
    cliente_id = criar_cliente()

    resposta = logado.http.post(f"/excluir/{cliente_id}")

    assert resposta.status_code == 400
    assert consultar_um("SELECT id FROM clientes WHERE id = %s", (cliente_id,))


def test_limite_de_tentativas_de_login(client, usuario):
    for _ in range(5):
        client.post("/login", data={"usuario": "admin", "senha": "errada"})

    bloqueado = client.post("/login", data={"usuario": "admin", "senha": SENHA})

    assert bloqueado.status_code == 429


# Clientes

def test_excluir_por_get_nao_funciona(logado):
    cliente_id = criar_cliente()

    assert logado.get(f"/excluir/{cliente_id}").status_code == 405
    assert consultar_um("SELECT id FROM clientes WHERE id = %s", (cliente_id,))


def test_excluir_remove_e_registra_historico(logado):
    cliente_id = criar_cliente(nome="João")

    assert logado.post(f"/excluir/{cliente_id}").status_code == 302
    assert consultar_um("SELECT id FROM clientes WHERE id = %s", (cliente_id,)) is None
    assert consultar_um("SELECT nome FROM historico_exclusoes")["nome"] == "João"


def test_cadastro_de_cliente(logado):
    assert logado.post("/novo", data=dados_cliente(nome="Ana")).status_code == 302
    assert consultar_um("SELECT nome FROM clientes")["nome"] == "Ana"


def test_cadastro_recusa_cpf_duplicado(logado):
    criar_cliente(cpf="111.111.111-11")

    resposta = logado.post("/novo", data=dados_cliente(nome="Outro", cpf="11111111111"))

    assert "Já existe um cliente cadastrado com esse CPF" in resposta.get_data(as_text=True)


def test_edicao_recusa_cpf_de_outro_cliente(logado):
    criar_cliente(nome="Ana", cpf="111.111.111-11")
    bruno = criar_cliente(nome="Bruno", cpf="222.222.222-22")

    resposta = logado.post(f"/editar/{bruno}", data=dados_cliente(nome="Bruno", cpf="111.111.111-11"))

    assert "Já existe outro cliente cadastrado com esse CPF" in resposta.get_data(as_text=True)
    assert consultar_um("SELECT cpf FROM clientes WHERE id = %s", (bruno,))["cpf"] == "222.222.222-22"


def test_edicao_mostra_erro_de_data(logado):
    cliente_id = criar_cliente()

    resposta = logado.post(f"/editar/{cliente_id}", data=dados_cliente(data_nascimento="31/02/2000"))

    assert "Data de nascimento inválida. Use DD/MM/AAAA." in resposta.get_data(as_text=True)


def test_edicao_valida_salva(logado):
    cliente_id = criar_cliente()

    logado.post(f"/editar/{cliente_id}", data=dados_cliente(nome="Maria Silva", cidade="Araraquara"))

    cliente = consultar_um("SELECT nome, cidade FROM clientes WHERE id = %s", (cliente_id,))
    assert cliente == {"nome": "Maria Silva", "cidade": "Araraquara"}


# Usuários

def test_novo_usuario_exige_senha_minima(logado):
    resposta = logado.post("/novo-usuario", data={
        "nome": "X", "usuario": "x", "email": "x@exemplo.com", "senha": "1234567",
    })

    assert "pelo menos 8 caracteres" in resposta.get_data(as_text=True)
    assert consultar_um("SELECT id FROM usuarios WHERE usuario = 'x'") is None


def test_comando_criar_usuario():
    runner = modulo.app.test_cli_runner()

    resultado = runner.invoke(args=[
        "criar-usuario", "--nome", "Dono", "--usuario", "dono",
        "--email", "Dono@Exemplo.com", "--senha", "segredo123",
    ])

    assert resultado.exit_code == 0, resultado.output
    criado = consultar_um("SELECT email, ativo FROM usuarios WHERE usuario = 'dono'")
    assert criado == {"email": "dono@exemplo.com", "ativo": 1}

    repetido = runner.invoke(args=[
        "criar-usuario", "--nome", "Dono", "--usuario", "dono",
        "--email", "dono@exemplo.com", "--senha", "segredo123",
    ])
    assert repetido.exit_code != 0
    assert "já cadastrado" in repetido.output

    curta = runner.invoke(args=[
        "criar-usuario", "--nome", "X", "--usuario", "x",
        "--email", "x@exemplo.com", "--senha", "1234567",
    ])
    assert curta.exit_code != 0


def test_primeiro_usuario_criado_pelo_comando_faz_login(client):
    modulo.app.test_cli_runner().invoke(args=[
        "criar-usuario", "--nome", "Dono", "--usuario", "dono",
        "--email", "dono@exemplo.com", "--senha", "segredo123",
    ])

    assert client.post("/login", data={"usuario": "dono", "senha": "segredo123"}).status_code == 302


# Recuperação de senha

def test_link_de_recuperacao_usa_app_url(client, usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: enviados.append(link))

    # O ProxyFix confia em X-Forwarded-Host: sem APP_URL, o link usaria esse endereço
    resposta = client.post(
        "/esqueci-senha",
        data={"email": usuario["email"]},
        headers={"X-Forwarded-Host": "site-falso.com"},
    )

    assert resposta.status_code == 200
    assert len(enviados) == 1
    assert enviados[0].startswith("https://clientes.exemplo.com/redefinir-senha/")
    assert "site-falso.com" not in enviados[0]


def test_recuperacao_nao_revela_emails_cadastrados(client, usuario, monkeypatch):
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: None)

    cadastrado = client.post("/esqueci-senha", data={"email": usuario["email"]}).get_data(as_text=True)
    inexistente = client.post("/esqueci-senha", data={"email": "nao@existe.com"}).get_data(as_text=True)

    assert "Se o e-mail estiver cadastrado" in cadastrado
    assert "Se o e-mail estiver cadastrado" in inexistente


def test_falha_no_envio_do_email_nao_quebra_a_pagina(client, usuario, monkeypatch):
    def falhar(email, link):
        raise Exception("Resend fora do ar")

    monkeypatch.setattr(modulo, "enviar_email_recuperacao", falhar)

    assert client.post("/esqueci-senha", data={"email": usuario["email"]}).status_code == 200


def test_redefinir_senha(client, usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(modulo, "enviar_email_recuperacao", lambda email, link: enviados.append(link))
    client.post("/esqueci-senha", data={"email": usuario["email"]})
    caminho = enviados[0].replace("https://clientes.exemplo.com", "")

    curta = client.post(caminho, data={"senha": "1234567", "confirmar_senha": "1234567"})
    assert "pelo menos 8 caracteres" in curta.get_data(as_text=True)

    ok = client.post(caminho, data={"senha": "novasenha1", "confirmar_senha": "novasenha1"})
    assert ok.status_code == 302

    assert client.post("/login", data={"usuario": "admin", "senha": "novasenha1"}).status_code == 302
    assert client.get(caminho).status_code == 400
