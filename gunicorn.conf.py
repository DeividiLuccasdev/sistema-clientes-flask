# O gunicorn carrega este arquivo sozinho quando é iniciado nesta pasta
# (o Render usa "gunicorn app:app"). As migrações rodam uma vez, no processo
# principal, antes de qualquer worker atender requisições.

from dotenv import load_dotenv


def on_starting(server):
    load_dotenv(override=True)

    from migrar import migrar

    migrar(log=server.log.info)
