// Evita envio duplicado: depois do primeiro submit, os botões do formulário
// ficam desabilitados. O servidor também é idempotente; isto só evita o
// segundo clique (ou o Enter repetido) chegar até ele.
document.addEventListener("submit", function (evento) {
    // Respeita um onsubmit que cancelou o envio (ex.: confirm() de exclusão)
    if (evento.defaultPrevented) {
        return;
    }

    const formulario = evento.target;

    if (formulario.dataset.enviando === "true") {
        evento.preventDefault();
        return;
    }

    formulario.dataset.enviando = "true";
    formulario.querySelectorAll("button[type=submit]").forEach(function (botao) {
        botao.disabled = true;
    });
});

// Ao voltar pelo histórico (cache do navegador), libera os formulários de novo
window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-enviando]").forEach(function (formulario) {
        delete formulario.dataset.enviando;
        formulario.querySelectorAll("button[type=submit]").forEach(function (botao) {
            botao.disabled = false;
        });
    });
});
