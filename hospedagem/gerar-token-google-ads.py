#!/usr/bin/env python3
"""Gera o refresh token do Google Ads com o Cliente Web 1 e grava os segredos no GitHub.

Uso (no Terminal, dentro da pasta dashboard-marketing):
    python3 hospedagem/gerar-token-google-ads.py

O script:
1. pede a chave secreta do cliente (GOCSPX-…), sem mostrar na tela;
2. abre o navegador para você autorizar com o login do Google Ads;
3. recebe a autorização em http://localhost:8765/ (endereço cadastrado no Cliente Web 1);
4. testa o token na Google Ads API;
5. grava GADS_CLIENT_ID, GADS_CLIENT_SECRET e GADS_REFRESH_TOKEN no repositório pelo gh.
Nenhum token é impresso.
"""
import getpass
import http.server
import json
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

CLIENT_ID = "786560950941-ugb0tdjeh8lerl6l3rhgvevn24v5beia.apps.googleusercontent.com"
REDIRECT = "http://localhost:8765/"
ESCOPO = "https://www.googleapis.com/auth/adwords"
REPO = "mktimds/painel-marketing-imendes"
GH = "/opt/homebrew/bin/gh"
API = "v26"


def gravar(nome, valor):
    r = subprocess.run([GH, "secret", "set", nome, "-R", REPO], input=valor, text=True,
                       capture_output=True)
    if r.returncode != 0:
        sys.exit(f"Falhou ao gravar {nome}: {r.stderr.strip()}")
    print(f"  ✓ {nome} gravado no GitHub")


def main():
    segredo = getpass.getpass("Cole a chave secreta do Cliente Web 1 (GOCSPX-…) e aperte Enter: ").strip()
    if not segredo.startswith("GOCSPX-"):
        sys.exit("Isso não parece a chave secreta: ela começa com GOCSPX-.")

    estado = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": ESCOPO, "access_type": "offline", "prompt": "consent", "state": estado})
    recebido = {}

    class Receptor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" not in q and "error" not in q:
                self.send_response(404); self.end_headers(); return
            recebido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Pronto. Pode fechar esta aba e voltar ao Terminal.</h2>".encode())

        def log_message(self, *a):
            pass

    servidor = http.server.HTTPServer(("localhost", 8765), Receptor)
    print("\nAbrindo o navegador. Entre com o login que administra o Google Ads (759-129-6003).")
    print("Se aparecer 'O Google não verificou este app': Avançado → Acessar Painel Marketing IMendes.\n")
    webbrowser.open(url)
    while not recebido:
        servidor.handle_request()
    servidor.server_close()

    if recebido.get("error"):
        sys.exit(f"O Google recusou a autorização: {recebido['error']}")
    if recebido.get("state") != estado:
        sys.exit("Resposta inesperada (state diferente). Rode de novo.")

    corpo = urllib.parse.urlencode({
        "code": recebido["code"], "client_id": CLIENT_ID, "client_secret": segredo,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", corpo, timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Falhou ao trocar o código: {e.read().decode()[:300]}")
    if "refresh_token" not in tok:
        sys.exit("O Google não devolveu refresh token. Rode de novo.")

    req = urllib.request.Request(f"https://googleads.googleapis.com/{API}/customers:listAccessibleCustomers",
                                 headers={"Authorization": f"Bearer {tok['access_token']}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            contas = json.load(r).get("resourceNames", [])
        print(f"Teste na Google Ads API: OK, {len(contas)} conta(s) acessível(is)"
              + (" — inclui a iMendes 759-129-6003" if "customers/7591296003" in contas else ""))
    except urllib.error.HTTPError as e:
        print(f"Aviso: o teste na Google Ads API respondeu {e.code}: {e.read().decode()[:300]}")

    print("\nGravando no GitHub…")
    gravar("GADS_CLIENT_ID", CLIENT_ID)
    gravar("GADS_CLIENT_SECRET", segredo)
    gravar("GADS_REFRESH_TOKEN", tok["refresh_token"])
    print("\nTudo certo. Avise o Claude para rodar o teste.")


if __name__ == "__main__":
    main()
