# Correções de bugs e segurança

Arquivos revisados para o projeto `sistema-clientes-flask`.

## Principais correções

- Remove a `SECRET_KEY` pública/conhecida e usa uma chave aleatória caso a variável de ambiente não esteja configurada.
- Ativa cookies de sessão `HttpOnly`, `SameSite=Lax` e `Secure` no Render.
- Adiciona proteção CSRF aos formulários POST.
- Altera a exclusão de cliente de GET para POST.
- Adiciona cabeçalhos HTTP de segurança.
- Limita tentativas de login e de recuperação de senha.
- Evita enumeração de e-mails na recuperação de senha.
- Exige senha com pelo menos 8 caracteres.
- Corrige validação de CPF duplicado também na edição.
- Usa uma conexão MySQL por request e fecha a conexão ao final da requisição.
- Remove consulta duplicada no dashboard.
- Corrige autocomplete para utilizar `todos_clientes`.
- Corrige HTML inválido no formulário de novo cliente.
- Adiciona timeout na chamada da API Resend.
- Desativa `debug=True` por padrão.

## Variáveis de ambiente recomendadas no Render

Defina pelo menos:

```text
SECRET_KEY=<uma chave aleatória forte>
SESSION_COOKIE_SECURE=true
```

A `SECRET_KEY` pode ser gerada localmente com:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Também mantenha configuradas as variáveis de banco e, se usar recuperação de senha, `RESEND_API_KEY`.

## Teste local

No `.env` local, use:

```text
SESSION_COOKIE_SECURE=false
```

Depois execute:

```bash
pip install -r requirements.txt
python app.py
```

Valide login, cadastro, edição, exclusão, criação de usuário e recuperação de senha antes do deploy.
