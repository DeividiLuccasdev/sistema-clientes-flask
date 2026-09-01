import os
import mysql.connector
import secrets
import smtplib
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, session, url_for
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv(override=True)

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "chave-temporaria-local")
conexao = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME") ,
    port=int(os.getenv("DB_PORT", "3306"))
)
app.secret_key = os.getenv("SECRET_KEY", "chave-temporaria-local")

conexao = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    port=int(os.getenv("DB_PORT", "3306"))
)
def verificar_conexao():
    global conexao

    if not conexao.is_connected():
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", "3306"))
        )

    return conexao


def enviar_email_recuperacao(destinatario, link):
    mensagem = EmailMessage()

    mensagem["Subject"] = "Recuperação de senha - Sistema de Clientes"
    mensagem["From"] = os.getenv("EMAIL_REMETENTE")
    mensagem["To"] = destinatario

    mensagem.set_content(
        f"""
Olá,

Recebemos uma solicitação para redefinir sua senha.

Clique no link abaixo:

{link}

Este link expira em 30 minutos.

Se você não solicitou a recuperação, ignore este e-mail.
"""
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(
            os.getenv("EMAIL_REMETENTE"),
            os.getenv("EMAIL_SENHA_APP")
        )
        smtp.send_message(mensagem)


# PÁGINA PRINCIPAL E PESQUISA
@app.route("/")
def inicio():
    if "usuario" not in session:
        return redirect("/login")

    busca = request.args.get("busca", "")

    cursor = conexao.cursor(dictionary=True)

    # Busca todos os nomes para o autocomplete
    cursor.execute("SELECT nome FROM clientes ORDER BY nome ASC")
    todos_clientes = cursor.fetchall()

    # Pesquisa da tabela
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

        cursor.execute(
            sql,
            (termo, termo, termo, termo, termo)
        )

    else:
        cursor.execute("SELECT * FROM clientes ORDER BY nome ASC")

    clientes = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) AS total FROM clientes")
    resultado_total = cursor.fetchone()
    total_clientes = resultado_total["total"]
    cursor.execute("""
    SELECT COUNT(*) AS novos
    FROM clientes
    WHERE MONTH(data_cadastro) = MONTH(CURRENT_DATE())
      AND YEAR(data_cadastro) = YEAR(CURRENT_DATE())
    """)

    resultado_novos = cursor.fetchone()
    novos_clientes = resultado_novos["novos"]
    cursor.execute("""
    SELECT COUNT(*) AS atualizados
    FROM clientes
    WHERE data_atualizacao IS NOT NULL
    AND MONTH(data_atualizacao) = MONTH(CURRENT_DATE())
    AND YEAR(data_atualizacao) = YEAR(CURRENT_DATE())
    """)

    resultado_atualizados = cursor.fetchone()
    clientes_atualizados = resultado_atualizados["atualizados"]
    cursor.execute("""
    SELECT COUNT(*) AS removidos
    FROM historico_exclusoes
    WHERE MONTH(data_exclusao) = MONTH(CURRENT_DATE())
    AND YEAR(data_exclusao) = YEAR(CURRENT_DATE())
    """)

    resultado_removidos = cursor.fetchone()
    clientes_removidos = resultado_removidos["removidos"]
    cursor.execute("""
    SELECT COUNT(*) AS removidos
    FROM historico_exclusoes
    WHERE MONTH(data_exclusao) = MONTH(CURRENT_DATE())
    AND YEAR(data_exclusao) = YEAR(CURRENT_DATE())
    """)

    resultado_removidos = cursor.fetchone()
    clientes_removidos = resultado_removidos["removidos"]

    return render_template(    
    "index.html",
    clientes=clientes,
    busca=busca,
    todos_clientes=todos_clientes,
    total_clientes=total_clientes,
    novos_clientes=novos_clientes ,
    clientes_atualizados=clientes_atualizados ,
    clientes_removidos=clientes_removidos
)
@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None

    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")

        cursor = conexao.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM usuarios WHERE usuario = %s AND ativo = TRUE",
            (usuario,)
        )

        dados_usuario = cursor.fetchone()
        cursor.close()

        if (
            dados_usuario
            and dados_usuario["senha"]
            and check_password_hash(dados_usuario["senha"], senha)
        ):
            session["usuario"] = dados_usuario["usuario"]
            session["nome"] = dados_usuario["nome"]
            return redirect("/")

        erro = "Usuário ou senha inválidos"

    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    mensagem = None
    erro = None

    if request.method == "POST":
        email = request.form.get("email")

        verificar_conexao()

        cursor = conexao.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, nome, usuario, email FROM usuarios WHERE email = %s AND ativo = TRUE",
            (email,)
        )

        usuario = cursor.fetchone()
        cursor.close()

        if usuario:
            token = secrets.token_urlsafe(32)
            expiracao = datetime.now() + timedelta(minutes=30)

            verificar_conexao()

            cursor = conexao.cursor()

            cursor.execute(
                """
                UPDATE usuarios
                SET token_recuperacao = %s,
                    token_expiracao = %s
                WHERE id = %s
                """,
                (token, expiracao, usuario["id"])
            )

            conexao.commit()
            cursor.close()

            link = url_for(
                 "redefinir_senha",
                token=token,
                _external=True
            )

            enviar_email_recuperacao(
                usuario["email"],
                link
            )

            mensagem = "E-mail de recuperação enviado com sucesso."

        else:
            erro = "E-mail não encontrado."
            

    return render_template(
        "esqueci_senha.html",
        mensagem=mensagem,
        erro=erro
    )
@app.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    cursor = conexao.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT id, usuario, token_expiracao
        FROM usuarios
        WHERE token_recuperacao = %s
        """,
        (token,)
    )

    usuario = cursor.fetchone()
    cursor.close()

    if not usuario:
        return "Link inválido ou expirado."

    if usuario["token_expiracao"] < datetime.now():
        return "Link inválido ou expirado."

    erro = None

    if request.method == "POST":
        senha = request.form.get("senha")
        confirmar_senha = request.form.get("confirmar_senha")

        if senha != confirmar_senha:
            erro = "As senhas não coincidem."
        else:
            senha_hash = generate_password_hash(senha)

            cursor = conexao.cursor()

            cursor.execute(
                """
                UPDATE usuarios
                SET senha = %s,
                    token_recuperacao = NULL,
                    token_expiracao = NULL
                WHERE id = %s
                """,
                (senha_hash, usuario["id"])
            )

            conexao.commit()
            cursor.close()

            return redirect("/login")

    return render_template(
        "redefinir_senha.html",
        erro=erro
    )

@app.route("/novo-usuario", methods=["GET", "POST"])
def novo_usuario():
    if "usuario" not in session:
        return redirect("/login")

    mensagem = None
    erro = None

    if request.method == "POST":
        nome = request.form.get("nome")
        usuario = request.form.get("usuario")
        email = request.form.get("email")
        senha = request.form.get("senha")

        senha_hash = generate_password_hash(senha)

        cursor = conexao.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO usuarios (nome, usuario, email, senha, ativo)
                VALUES (%s, %s, %s, %s, TRUE)
                """,
                (nome, usuario, email, senha_hash)
            )

            conexao.commit()
            mensagem = "Usuário cadastrado com sucesso."

        except mysql.connector.IntegrityError:
            conexao.rollback()
            erro = "Usuário ou e-mail já cadastrado."

        finally:
            cursor.close()

    return render_template(
        "novo_usuario.html",
        mensagem=mensagem,
        erro=erro
    )


# CADASTRAR NOVO CLIENTE
@app.route("/novo", methods=["GET", "POST"])
def novo_cliente():
    if "usuario" not in session:
        return redirect("/login")

    if request.method == "POST":

        nome = request.form["nome"]
        telefone = request.form["telefone"]
        email = request.form["email"]
        cpf = request.form["cpf"]
        cidade = request.form["cidade"]
        data_nascimento = request.form["data_nascimento"]

        # Validar e converter a data
        try:
            data_nascimento_mysql = datetime.strptime(
                data_nascimento,
                "%d/%m/%Y"
            ).strftime("%Y-%m-%d")

        except ValueError:
            return render_template(
                "novo_cliente.html",
                erro="Data de nascimento inválida. Use o formato DD/MM/AAAA.",
                nome=nome,
                telefone=telefone,
                email=email,
                cpf=cpf,
                cidade=cidade,
                data_nascimento=data_nascimento
            )

        # Remove pontos e traço do CPF para comparação
        cpf_limpo = cpf.replace(".", "").replace("-", "")

        cursor = conexao.cursor(dictionary=True)

        # Verificar CPF duplicado
        cursor.execute(
            """
            SELECT * FROM clientes
            WHERE REPLACE(REPLACE(cpf, '.', ''), '-', '') = %s
            """,
            (cpf_limpo,)
        )

        cliente_existente = cursor.fetchone()

        if cliente_existente:
            return render_template(
                "novo_cliente.html",
                erro="Já existe um cliente cadastrado com esse CPF!",
                nome=nome,
                telefone=telefone,
                email=email,
                cpf=cpf,
                cidade=cidade,
                data_nascimento=data_nascimento
            )

        # Cadastrar cliente
        sql = """
        INSERT INTO clientes (
            nome,
            telefone,
            email,
            cpf,
            cidade,
            data_nascimento
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """

        valores = (
            nome,
            telefone,
            email,
            cpf,
            cidade,
            data_nascimento_mysql
        )

        cursor.execute(sql, valores)
        conexao.commit()

        return redirect("/")

    return render_template("novo_cliente.html")

# EXCLUIR CLIENTE
@app.route("/excluir/<int:id>")
def excluir_cliente(id):
    if "usuario" not in session:
        return redirect("/login")

    cursor = conexao.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, nome FROM clientes WHERE id = %s",
        (id,)
    )

    cliente = cursor.fetchone()

    if cliente:

        cursor.execute(
            """
            INSERT INTO historico_exclusoes (cliente_id, nome)
            VALUES (%s, %s)
            """,
            (cliente["id"], cliente["nome"])
        )

        cursor.execute(
            "DELETE FROM clientes WHERE id = %s",
            (id,)
        )

        conexao.commit()

    return redirect("/")


# EDITAR CLIENTE
@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar_cliente(id):
    if "usuario" not in session:
        return redirect("/login")

    if request.method == "POST":
        nome = request.form["nome"]
        telefone = request.form["telefone"]
        email = request.form["email"]
        cpf = request.form["cpf"]
        cidade = request.form["cidade"]
        data_nascimento = request.form["data_nascimento"]

        try:
            data_nascimento_mysql = datetime.strptime(
                data_nascimento,
                "%d/%m/%Y"
            ).strftime("%Y-%m-%d")

        except ValueError:
            cursor = conexao.cursor(dictionary=True)

            cursor.execute(
                "SELECT * FROM clientes WHERE id = %s",
                (id,)
            )

            cliente = cursor.fetchone()

            return render_template(
                "editar_cliente.html",
                cliente=cliente,
                erro="Data de nascimento inválida. Use DD/MM/AAAA."
            )

        cursor = conexao.cursor()

        sql = """
        UPDATE clientes
        SET nome = %s,
            telefone = %s,
            email = %s,
            cpf = %s,
            cidade = %s,
            data_nascimento = %s,
            data_atualizacao = CURRENT_TIMESTAMP
        WHERE id = %s
        """

        valores = (
            nome,
            telefone,
            email,
            cpf,
            cidade,
            data_nascimento_mysql,
            id
        )

        cursor.execute(sql, valores)
        conexao.commit()

        return redirect("/")

    cursor = conexao.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM clientes WHERE id = %s",
        (id,)
    )

    cliente = cursor.fetchone()

    return render_template(
        "editar_cliente.html",
        cliente=cliente
    )
  


if __name__ == "__main__":
    app.run(debug=True)