#!/bin/sh
# Testa o login do FTP do painel (o mesmo que vai nos segredos DASH_UPLOAD_USER e DASH_UPLOAD_PASS).
# Pergunta o login; a senha é pedida pelo curl e não aparece na tela.
printf 'Login da conta FTP (como o cPanel mostra, ex.: painel@grupoimendes.com.br): '
read -r LOGIN
printf 'O login tem %s caracteres.\n' "$(printf '%s' "$LOGIN" | wc -c | tr -d ' ')"
if curl -sS --ssl-reqd --user "$LOGIN" --list-only ftp://br.jyn5040.com.br/; then
  echo ""
  echo "OK: login e senha certos. Coloque exatamente esses dois nos segredos do GitHub."
else
  echo ""
  echo "FALHOU: se apareceu 530, o login ou a senha estão errados (ou o servidor bloqueou por tentativas)."
fi
