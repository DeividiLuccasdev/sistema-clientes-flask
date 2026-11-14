"""Conta pública de demonstração (credenciais publicadas no README).

O gunicorn.conf.py chama garantir_usuario_demo() logo depois das migrações.
Só cria a conta no Render (variável RENDER, definida pelo próprio Render) ou com
CRIAR_USUARIO_DEMO=true, para não sujar bancos locais e de teste.

Se a conta já existe, volta a ficar ativa e com a senha conhecida: uma demo
alterada por um visitante se recupera a cada deploy.
"""

import os

from werkzeug.security import generate_password_hash

DEMO_NOME = "Usuário Demo"
DEMO_USUARIO = "demo"
DEMO_EMAIL = "demo@example.com"
DEMO_SENHA = "Demo@2026"


def eh_usuario_demo(usuario=None, email=None):
    """True se o nome de usuário ou o e-mail são os da conta de demonstração."""

    if usuario and usuario.strip().lower() == DEMO_USUARIO:
        return True
    return bool(email and email.strip().lower() == DEMO_EMAIL)


def deve_criar_usuario_demo():
    return bool(os.getenv("RENDER")) or os.getenv("CRIAR_USUARIO_DEMO", "").lower() == "true"


def garantir_usuario_demo(log=print, conectar=None):
    """Cria ou restaura a conta demo. Devolve True se agiu, False se pulou."""

    if not deve_criar_usuario_demo():
        log("usuário demo: ignorado (defina CRIAR_USUARIO_DEMO=true para criar)")
        return False

    if conectar is None:
        from migrar import conectar

    senha_hash = generate_password_hash(DEMO_SENHA)
    db = conectar()
    cursor = db.cursor()
    try:
        # Um único comando: dois processos subindo juntos não geram erro de
        # duplicidade, e o UNIQUE de usuario/email garante uma só conta.
        cursor.execute(
            """
            INSERT INTO usuarios (nome, usuario, email, senha, ativo)
            VALUES (%s, %s, %s, %s, TRUE)
            ON DUPLICATE KEY UPDATE
                nome = %s,
                senha = %s,
                ativo = TRUE,
                token_recuperacao = NULL,
                token_expiracao = NULL
            """,
            (DEMO_NOME, DEMO_USUARIO, DEMO_EMAIL, senha_hash, DEMO_NOME, senha_hash),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()

    log("usuário demo: pronto")
    return True
