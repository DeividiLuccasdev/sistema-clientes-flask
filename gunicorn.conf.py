# O gunicorn carrega este arquivo sozinho quando é iniciado nesta pasta
# (o Render usa "gunicorn app:app"). As migrações rodam uma vez, no processo
# principal, antes de qualquer worker atender requisições. Em seguida, a conta
# de demonstração é criada/restaurada (só no Render; veja usuario_demo.py).

from dotenv import load_dotenv


def on_starting(server):
    load_dotenv(override=True)

    from migrar import migrar
    from usuario_demo import garantir_usuario_demo

    migrar(log=server.log.info)
    garantir_usuario_demo(log=server.log.info)
