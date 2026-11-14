import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

import click
import mysql.connector
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    get_flashed_messages,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from mysql.connector import errorcode
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv(override=True)



app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)



secret_key = os.getenv("SECRET_KEY")

if not secret_key:

    # Fallback aleatório evita uma chave pública conhecida. Em produção,

    # configure SECRET_KEY no ambiente para manter as sessões entre reinícios.

    secret_key = secrets.token_hex(32)

app.secret_key = secret_key

app.config.update(

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=(

        os.getenv(

            "SESSION_COOKIE_SECURE",

            "true" if os.getenv("RENDER") else "false",

        ).lower()

        == "true"

    ),

    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),

)






def obter_conexao():

    if "db" not in g:

        ultimo_erro = None



        for tentativa in range(3):

            try:

                g.db = mysql.connector.connect(

                    host=os.getenv("DB_HOST"),

                    user=os.getenv("DB_USER"),

                    password=os.getenv("DB_PASSWORD"),

                    database=os.getenv("DB_NAME"),

                    port=int(os.getenv("DB_PORT", "3306")),

                    connection_timeout=10,

                )

                break

            except mysql.connector.Error as erro:

                ultimo_erro = erro

                if tentativa < 2:

                    time.sleep(2)



        if "db" not in g:

            raise ultimo_erro



    return g.db





@app.teardown_appcontext

def fechar_conexao(_erro=None):

    db = g.pop("db", None)



    if db is not None:

        try:

            if db.is_connected():

                db.close()

        except mysql.connector.Error:

            pass





def login_required(func):

    @wraps(func)

    def wrapper(*args, **kwargs):

        if "usuario" not in session:

            return redirect(url_for("login"))



        return func(*args, **kwargs)



    return wrapper





def gerar_csrf_token():

    token = session.get("_csrf_token")



    if not token:

        token = secrets.token_urlsafe(32)

        session["_csrf_token"] = token



    return token





app.jinja_env.globals["csrf_token"] = gerar_csrf_token





@app.before_request

def validar_csrf():

    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:

        return None



    token_sessao = session.get("_csrf_token")

    token_enviado = request.form.get("_csrf_token") or request.headers.get(

        "X-CSRF-Token"

    )



    if (

        not token_sessao

        or not token_enviado

        or not secrets.compare_digest(token_sessao, token_enviado)

    ):

        abort(400, description="Token CSRF inválido ou ausente.")



    return None





@app.after_request

def adicionar_cabecalhos_seguranca(response):

    response.headers["X-Content-Type-Options"] = "nosniff"

    response.headers["X-Frame-Options"] = "SAMEORIGIN"

    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    return response





def obter_ip_cliente():

    # No Render, request.remote_addr representa o proxy/cliente conforme a

    # configuração do servidor. Evitamos confiar diretamente em X-Forwarded-For.

    return request.remote_addr or "desconhecido"





LIMITE_TENTATIVAS = 5

JANELA_TENTATIVAS_SEGUNDOS = 900


def chave_limite(*partes):
    # Hash para caber na coluna (o usuário digitado não tem tamanho máximo)
    # e para não gravar IP/usuário em texto puro.
    return hashlib.sha256(":".join(partes).encode()).hexdigest()


def registrar_tentativa(chave, janela_segundos=JANELA_TENTATIVAS_SEGUNDOS):
    """Conta mais uma tentativa para a chave e devolve o total na janela atual.

    A contagem fica no MySQL, compartilhada entre workers, e é feita por um
    único upsert: a linha fica travada até o commit, então requisições
    simultâneas recebem valores diferentes (1, 2, 3...) e o limite não é
    furado. A tentativa é registrada antes de conferir a senha.
    """

    db = obter_conexao()

    for tentativa in range(3):
        cursor = db.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO tentativas_acesso (chave, tentativas, janela_inicio)
                VALUES (%s, 1, NOW())
                ON DUPLICATE KEY UPDATE
                    tentativas = IF(
                        janela_inicio <= NOW() - INTERVAL %s SECOND, 1, tentativas + 1
                    ),
                    janela_inicio = IF(
                        janela_inicio <= NOW() - INTERVAL %s SECOND, NOW(), janela_inicio
                    )
                """,
                (chave, janela_segundos, janela_segundos),
            )
            cursor.execute(
                "SELECT tentativas FROM tentativas_acesso WHERE chave = %s", (chave,)
            )
            (tentativas,) = cursor.fetchone()
            db.commit()
            return tentativas
        except mysql.connector.Error as erro:
            db.rollback()
            # Vários INSERTs simultâneos da mesma chave nova podem gerar
            # deadlock no InnoDB; o MySQL desfaz um deles e basta repetir.
            if erro.errno != errorcode.ER_LOCK_DEADLOCK or tentativa == 2:
                raise
        except Exception:
            db.rollback()
            raise
        finally:
            cursor.close()


def limpar_tentativas(chave):
    db = obter_conexao()
    cursor = db.cursor()

    try:
        cursor.execute("DELETE FROM tentativas_acesso WHERE chave = %s", (chave,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cpf_somente_digitos(cpf):
    # Mesma regra da coluna gerada clientes.cpf_digitos
    return re.sub(r"[^0-9]", "", cpf)


def e_duplicidade(erro):
    return erro.errno == errorcode.ER_DUP_ENTRY





def enviar_email_recuperacao(destinatario, link):

    import requests



    api_key = os.getenv("RESEND_API_KEY")



    if not api_key:

        raise RuntimeError("RESEND_API_KEY não configurada.")



    resposta = requests.post(

        "https://api.resend.com/emails",

        headers={

            "Authorization": f"Bearer {api_key}",

            "Content-Type": "application/json",

        },

        json={

            "from": "Sistema de Clientes <onboarding@resend.dev>",

            "to": [destinatario],

            "subject": "Recuperação de senha - Sistema de Clientes",

            "text": f"""

Olá,



Recebemos uma solicitação para redefinir sua senha.



Clique no link abaixo:



{link}



Este link expira em 30 minutos.



Se você não solicitou a recuperação, ignore este e-mail.

""",

        },

        timeout=15,

    )



    if resposta.status_code not in (200, 201):

        raise RuntimeError(f"Erro ao enviar e-mail: {resposta.text}")





# PÁGINA PRINCIPAL E PESQUISA

@app.route("/")

@login_required

def inicio():

    db = obter_conexao()

    busca = request.args.get("busca", "").strip()

    cursor = db.cursor(dictionary=True)



    try:

        cursor.execute("SELECT nome FROM clientes ORDER BY nome ASC")

        todos_clientes = cursor.fetchall()



        if busca:

            sql = """

            SELECT * FROM clientes

            WHERE nome LIKE %s

               OR telefone LIKE %s

               OR email LIKE %s

               OR cpf LIKE %s

               OR cidade LIKE %s

            ORDER BY nome ASC

            """

            termo = f"%{busca}%"

            cursor.execute(sql, (termo, termo, termo, termo, termo))

        else:

            cursor.execute("SELECT * FROM clientes ORDER BY nome ASC")



        clientes = cursor.fetchall()



        cursor.execute("SELECT COUNT(*) AS total FROM clientes")

        total_clientes = cursor.fetchone()["total"]



        cursor.execute(

            """

            SELECT COUNT(*) AS novos

            FROM clientes

            WHERE MONTH(data_cadastro) = MONTH(CURRENT_DATE())

              AND YEAR(data_cadastro) = YEAR(CURRENT_DATE())

            """

        )

        novos_clientes = cursor.fetchone()["novos"]



        cursor.execute(

            """

            SELECT COUNT(*) AS atualizados

            FROM clientes

            WHERE data_atualizacao IS NOT NULL

              AND MONTH(data_atualizacao) = MONTH(CURRENT_DATE())

              AND YEAR(data_atualizacao) = YEAR(CURRENT_DATE())

            """

        )

        clientes_atualizados = cursor.fetchone()["atualizados"]



        cursor.execute(

            """

            SELECT COUNT(*) AS removidos

            FROM historico_exclusoes

            WHERE MONTH(data_exclusao) = MONTH(CURRENT_DATE())

              AND YEAR(data_exclusao) = YEAR(CURRENT_DATE())

            """

        )

        clientes_removidos = cursor.fetchone()["removidos"]

    finally:

        cursor.close()



    return render_template(

        "index.html",

        clientes=clientes,

        busca=busca,

        todos_clientes=todos_clientes,

        total_clientes=total_clientes,

        novos_clientes=novos_clientes,

        clientes_atualizados=clientes_atualizados,

        clientes_removidos=clientes_removidos,

    )





@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        chave = chave_limite("login", obter_ip_cliente(), usuario.lower())

        # Conta a tentativa antes de conferir a senha: com "verifica e depois
        # registra", requisições em paralelo passavam todas pela verificação.
        if registrar_tentativa(chave) > LIMITE_TENTATIVAS:
            erro = "Muitas tentativas de login. Tente novamente em alguns minutos."
            return render_template("login.html", erro=erro), 429

        db = obter_conexao()
        cursor = db.cursor(dictionary=True)

        try:
            cursor.execute(
                "SELECT * FROM usuarios WHERE usuario = %s AND ativo = TRUE",
                (usuario,),
            )
            dados_usuario = cursor.fetchone()
        finally:
            cursor.close()

        if (
            dados_usuario
            and dados_usuario.get("senha")
            and check_password_hash(dados_usuario["senha"], senha)
        ):
            limpar_tentativas(chave)
            session.clear()
            session.permanent = True
            session["usuario"] = dados_usuario["usuario"]
            session["nome"] = dados_usuario["nome"]
            gerar_csrf_token()
            return redirect(url_for("inicio"))

        erro = "Usuário ou senha inválidos"

    return render_template("login.html", erro=erro)






@app.route("/logout")

def logout():

    session.clear()

    return redirect(url_for("login"))





# Endereço público usado nos links enviados por e-mail (ex.: https://seu-app.onrender.com).
# Com APP_URL definido, o link não depende do cabeçalho Host da requisição,
# que pode ser alterado por quem pede a recuperação de senha.
APP_URL = os.getenv("APP_URL", "").rstrip("/")


def montar_link_publico(caminho):
    if APP_URL:
        return APP_URL + caminho

    app.logger.warning(
        "APP_URL não configurado: o link de recuperação usa o endereço da requisição."
    )
    return request.url_root.rstrip("/") + caminho


@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    mensagem = None
    erro = None

    if request.method == "POST":
        chave = chave_limite("recuperacao", obter_ip_cliente())

        if registrar_tentativa(chave) > LIMITE_TENTATIVAS:
            erro = "Muitas solicitações. Tente novamente em alguns minutos."
            return render_template(
                "esqueci_senha.html", mensagem=mensagem, erro=erro
            ), 429

        email = request.form.get("email", "").strip().lower()
        db = obter_conexao()
        cursor = db.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT id, nome, usuario, email
                FROM usuarios
                WHERE email = %s AND ativo = TRUE
                """,
                (email,),
            )
            usuario = cursor.fetchone()
        finally:
            cursor.close()

        if usuario:
            token = secrets.token_urlsafe(32)
            cursor = db.cursor()

            try:
                # Só o hash do token vai para o banco. A expiração usa o relógio
                # do MySQL, o mesmo que valida o token depois.
                cursor.execute(
                    """
                    UPDATE usuarios
                    SET token_recuperacao = %s,
                        token_expiracao = NOW() + INTERVAL 30 MINUTE
                    WHERE id = %s
                    """,
                    (hash_token(token), usuario["id"]),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                cursor.close()

            link = montar_link_publico(url_for("redefinir_senha", token=token))

            try:
                enviar_email_recuperacao(usuario["email"], link)
            except Exception:
                app.logger.exception("Falha ao enviar e-mail de recuperação")

        mensagem = (
            "Se o e-mail estiver cadastrado, você receberá as instruções "
            "para redefinição da senha."
        )

    return render_template(
        "esqueci_senha.html",
        mensagem=mensagem,
        erro=erro,
    )


LINK_INVALIDO = ("Link inválido ou expirado.", 400)


@app.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    token_hash = hash_token(token)
    db = obter_conexao()
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id
            FROM usuarios
            WHERE token_recuperacao = %s
              AND token_expiracao > NOW()
            """,
            (token_hash,),
        )
        usuario = cursor.fetchone()
    finally:
        cursor.close()

    if not usuario:
        return LINK_INVALIDO

    erro = None

    if request.method == "POST":
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if senha != confirmar_senha:
            erro = "As senhas não coincidem."
        elif len(senha) < 8:
            erro = "A senha deve ter pelo menos 8 caracteres."
        else:
            cursor = db.cursor()

            try:
                # Consome o token na mesma instrução que troca a senha: se duas
                # requisições chegarem juntas, só uma encontra o token válido.
                cursor.execute(
                    """
                    UPDATE usuarios
                    SET senha = %s,
                        token_recuperacao = NULL,
                        token_expiracao = NULL
                    WHERE id = %s
                      AND token_recuperacao = %s
                      AND token_expiracao > NOW()
                    """,
                    (generate_password_hash(senha), usuario["id"], token_hash),
                )
                consumido = cursor.rowcount == 1
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                cursor.close()

            if not consumido:
                return LINK_INVALIDO

            return redirect(url_for("login"))

    return render_template("redefinir_senha.html", erro=erro)


@app.route("/novo-usuario", methods=["GET", "POST"])
@login_required
def novo_usuario():
    erro = None

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario = request.form.get("usuario", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        if len(senha) < 8:
            erro = "A senha deve ter pelo menos 8 caracteres."
        else:
            senha_hash = generate_password_hash(senha)
            db = obter_conexao()
            cursor = db.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO usuarios (nome, usuario, email, senha, ativo)
                    VALUES (%s, %s, %s, %s, TRUE)
                    """,
                    (nome, usuario, email, senha_hash),
                )
                db.commit()
            except mysql.connector.IntegrityError as falha:
                db.rollback()
                if not e_duplicidade(falha):
                    raise
                erro = "Usuário ou e-mail já cadastrado."
            except Exception:
                db.rollback()
                raise
            finally:
                cursor.close()

            if not erro:
                # Post/Redirect/Get: recarregar a página não reenvia o cadastro
                flash("Usuário cadastrado com sucesso.")
                return redirect(url_for("novo_usuario"))

    mensagens = get_flashed_messages()

    return render_template(
        "novo_usuario.html",
        mensagem=mensagens[0] if mensagens else None,
        erro=erro,
    )


@app.route("/novo", methods=["GET", "POST"])
@login_required
def novo_cliente():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        telefone = request.form.get("telefone", "").strip()
        email = request.form.get("email", "").strip().lower()
        cpf = request.form.get("cpf", "").strip()
        cidade = request.form.get("cidade", "").strip()
        data_nascimento = request.form.get("data_nascimento", "").strip()

        def formulario_com_erro(erro):
            return render_template(
                "novo_cliente.html",
                erro=erro,
                nome=nome,
                telefone=telefone,
                email=email,
                cpf=cpf,
                cidade=cidade,
                data_nascimento=data_nascimento,
            )

        try:
            data_nascimento_obj = datetime.strptime(
                data_nascimento,
                "%d/%m/%Y",
            ).date()
        except ValueError:
            return formulario_com_erro(
                "Data de nascimento inválida. Use o formato DD/MM/AAAA."
            )

        if data_nascimento_obj > datetime.now().date():
            return formulario_com_erro("A data de nascimento não pode ser futura.")

        data_nascimento_mysql = data_nascimento_obj.strftime("%Y-%m-%d")
        erro_cpf = "Já existe um cliente cadastrado com esse CPF!"

        db = obter_conexao()
        cursor = db.cursor(dictionary=True)

        try:
            # Consulta prévia só para a mensagem amigável no caso comum. Quem
            # garante a unicidade é o índice UNIQUE de clientes.cpf_digitos.
            cursor.execute(
                "SELECT id FROM clientes WHERE cpf_digitos = %s",
                (cpf_somente_digitos(cpf),),
            )
            if cursor.fetchone():
                return formulario_com_erro(erro_cpf)

            cursor.execute(
                """
                INSERT INTO clientes (
                    nome,
                    telefone,
                    email,
                    cpf,
                    cidade,
                    data_nascimento
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (nome, telefone, email, cpf, cidade, data_nascimento_mysql),
            )
            db.commit()
        except mysql.connector.IntegrityError as falha:
            # Outro cadastro com o mesmo CPF entrou entre a consulta e o INSERT
            db.rollback()
            if not e_duplicidade(falha):
                raise
            return formulario_com_erro(erro_cpf)
        except Exception:
            db.rollback()
            raise
        finally:
            cursor.close()

        return redirect(url_for("inicio"))

    return render_template("novo_cliente.html")


@app.route("/excluir/<int:id>", methods=["POST"])
@login_required
def excluir_cliente(id):
    db = obter_conexao()
    cursor = db.cursor(dictionary=True)

    try:
        # FOR UPDATE trava a linha: uma segunda exclusão simultânea espera esta
        # terminar, não encontra mais o cliente e não grava outro histórico.
        cursor.execute(
            "SELECT id, nome FROM clientes WHERE id = %s FOR UPDATE", (id,)
        )
        cliente = cursor.fetchone()

        if cliente:
            cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))

            if cursor.rowcount == 1:
                cursor.execute(
                    """
                    INSERT INTO historico_exclusoes (cliente_id, nome)
                    VALUES (%s, %s)
                    """,
                    (cliente["id"], cliente["nome"]),
                )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()

    return redirect(url_for("inicio"))


def buscar_cliente(db, id):
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
        return cursor.fetchone()
    finally:
        cursor.close()


ERRO_CONFLITO_EDICAO = (
    "Este cliente foi alterado por outra pessoa enquanto você editava. "
    "Os dados atuais foram carregados abaixo; revise e salve novamente."
)


@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_cliente(id):
    db = obter_conexao()

    if request.method == "GET":
        cliente = buscar_cliente(db, id)

        if not cliente:
            abort(404)

        return render_template("editar_cliente.html", cliente=cliente)

    campos = {
        "nome": request.form.get("nome", "").strip(),
        "telefone": request.form.get("telefone", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "cpf": request.form.get("cpf", "").strip(),
        "cidade": request.form.get("cidade", "").strip(),
    }
    data_nascimento = request.form.get("data_nascimento", "").strip()

    try:
        versao = int(request.form.get("versao", ""))
    except ValueError:
        versao = None

    def formulario_com_erro(erro, data_nascimento_obj=None):
        # Mantém o que a pessoa digitou e a versão que ela estava editando
        cliente = buscar_cliente(db, id)

        if not cliente:
            abort(404)

        cliente.update(campos)
        cliente["versao"] = versao
        if data_nascimento_obj:
            cliente["data_nascimento"] = data_nascimento_obj

        return render_template("editar_cliente.html", cliente=cliente, erro=erro)

    def conflito():
        cliente = buscar_cliente(db, id)

        if not cliente:
            abort(404)

        return render_template(
            "editar_cliente.html", cliente=cliente, erro=ERRO_CONFLITO_EDICAO
        ), 409

    if versao is None:
        return conflito()

    try:
        data_nascimento_obj = datetime.strptime(
            data_nascimento,
            "%d/%m/%Y",
        ).date()
    except ValueError:
        return formulario_com_erro("Data de nascimento inválida. Use DD/MM/AAAA.")

    if data_nascimento_obj > datetime.now().date():
        return formulario_com_erro(
            "A data de nascimento não pode ser futura.", data_nascimento_obj
        )

    erro_cpf = "Já existe outro cliente cadastrado com esse CPF!"
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT id FROM clientes WHERE cpf_digitos = %s AND id <> %s",
            (cpf_somente_digitos(campos["cpf"]), id),
        )
        cpf_em_uso = cursor.fetchone() is not None

        atualizado = False
        if not cpf_em_uso:
            # Trava otimista: só grava se ninguém salvou desde que o formulário
            # foi aberto. Sem isso, a última gravação apagava a anterior.
            cursor.execute(
                """
                UPDATE clientes
                SET nome = %s,
                    telefone = %s,
                    email = %s,
                    cpf = %s,
                    cidade = %s,
                    data_nascimento = %s,
                    data_atualizacao = CURRENT_TIMESTAMP,
                    versao = versao + 1
                WHERE id = %s AND versao = %s
                """,
                (
                    campos["nome"],
                    campos["telefone"],
                    campos["email"],
                    campos["cpf"],
                    campos["cidade"],
                    data_nascimento_obj.strftime("%Y-%m-%d"),
                    id,
                    versao,
                ),
            )
            atualizado = cursor.rowcount == 1

        db.commit()
    except mysql.connector.IntegrityError as falha:
        # Outro cliente recebeu este CPF entre a consulta e o UPDATE
        db.rollback()
        if not e_duplicidade(falha):
            raise
        cpf_em_uso = True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()

    if cpf_em_uso:
        return formulario_com_erro(erro_cpf, data_nascimento_obj)

    if not atualizado:
        # Versão diferente (alguém salvou antes) ou cliente excluído (404)
        return conflito()

    return redirect(url_for("inicio"))


# CRIAR USUÁRIO PELO TERMINAL
# Como a tela "Novo usuário" exige login, o primeiro acesso é criado com:
#   flask --app app criar-usuario
@app.cli.command("criar-usuario")
@click.option("--nome", prompt="Nome")
@click.option("--usuario", prompt="Usuário")
@click.option("--email", prompt="E-mail")
@click.password_option("--senha", prompt="Senha", confirmation_prompt="Confirme a senha")
def criar_usuario(nome, usuario, email, senha):
    if len(senha) < 8:
        raise click.ClickException("A senha deve ter pelo menos 8 caracteres.")

    db = obter_conexao()
    cursor = db.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO usuarios (nome, usuario, email, senha, ativo)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (nome.strip(), usuario.strip(), email.strip().lower(), generate_password_hash(senha)),
        )
        db.commit()
    except mysql.connector.IntegrityError:
        db.rollback()
        raise click.ClickException("Usuário ou e-mail já cadastrado.")
    finally:
        cursor.close()

    click.echo(f"Usuário {usuario.strip()} criado com sucesso.")


if __name__ == "__main__":

    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
