import os
import mysql.connector
from flask import Flask, render_template, request, redirect
from dotenv import load_dotenv
from datetime import datetime
load_dotenv(override=True)
app = Flask(__name__)

conexao = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)


# PÁGINA PRINCIPAL E PESQUISA
@app.route("/")
def inicio():
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


# CADASTRAR NOVO CLIENTE
@app.route("/novo", methods=["GET", "POST"])
def novo_cliente():

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