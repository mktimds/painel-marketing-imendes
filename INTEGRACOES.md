# Painel de Marketing IMendes — como integrar cada fonte

O painel tem três partes:

1. **`index.html` + `logo-imendes-branca.png`**: a página. Sobe uma vez no site, numa pasta protegida por senha.
2. **`coletar_dados.py`**: busca os números em cada plataforma e grava `dados.json`.
3. **GitHub Actions** (`.github/workflows/atualizar-painel.yml`): roda o script a cada 10 min e envia o `dados.json` para a mesma pasta do site.

A página relê o `dados.json` a cada 10 min sozinha, com contador regressivo e animação.
Os dados vêm **por dia** (últimos 180 dias, mude com `DIAS_HISTORICO`), e o botão **Período** soma qualquer intervalo de datas no navegador.
O **alcance** do Meta (pessoas únicas) não pode ser somado por dia: ele aparece só nos períodos prontos (mês atual, mês anterior, 7, 30 e 90 dias, tudo).
Cada aba tem um funil: plataforma (impressões, alcance, cliques, leads) → contatos no HubSpot daquela origem → negócios no pré-vendas → oportunidades qualificadas (SQL).
A atribuição ao HubSpot usa só a origem original registrada (`hs_analytics_source`); leads cadastrados à mão, como os do WhatsApp, aparecem na aba WhatsApp pelo *Canal de entrada*.
Nenhum token fica no HTML: os tokens ficam só nos *Secrets* do GitHub.

## Situação em 13/11/2026

| Fonte | Situação | O que falta |
|---|---|---|
| Meta Ads | ✅ funcionando (testado) | Só cadastrar o segredo `META_ACCESS_TOKEN` no GitHub |
| HubSpot | ✅ funcionando (testado) | Cadastrar `HUBSPOT_TOKEN` (de preferência um app privado só de leitura) |
| Google Ads | ⚠️ cópia manual do Reportei (13/11, 9h20) | Configurar a Google Ads API (passo 3) |
| GA4 (cliques no WhatsApp) | ⏳ pendente | Conta de serviço (passo 4) e confirmar o nome do evento |
| LinkedIn Ads | ⏳ sem números | Conta com campanhas + app aprovado (passo 5) |

---

## 1. Meta Ads (Facebook e Instagram)

Já funciona com o token do usuário do sistema do app **API MKT** (o mesmo de `env/TkImendes.env`).

- Segredo no GitHub: `META_ACCESS_TOKEN` = o valor depois de `META_ACCESS_TOKEN=` no arquivo.
- Contas lidas: act_1248772976109746, act_3464964433774316, act_704326994947485, act_996622288759693.
  Para mudar, crie o segredo/variável `META_AD_ACCOUNTS` com os IDs separados por vírgula.

**O que o painel conta como resultado no Meta**

- Leads de formulário instantâneo (`onsite_conversion.lead_grouped`)
- Conversas iniciadas no WhatsApp (`onsite_conversion.messaging_conversation_started_7d`)
- Leads do site pelo pixel (`offsite_conversion.fb_pixel_lead`)

O campo `actions_lead` não é usado, porque subconta campanhas de WhatsApp.
Os leads de pixel de **03 e 04/11/2026** são descontados: nesses dias o snippet WPCode disparava Lead em cliques de WhatsApp/CTA (2.393 eventos). O painel mostra o aviso. Para tirar ou mudar os dias, edite `META_PIXEL_DIAS_INVALIDOS` no script.

## 2. HubSpot

- Segredo: `HUBSPOT_TOKEN`.
- Recomendado: criar um app privado novo, **só leitura**, em Configurações → Integrações → Apps privados, com os escopos
  `crm.objects.contacts.read` e `crm.objects.deals.read`. Assim o token do painel não pode alterar nada no CRM.
- O que o painel lê:
  - **Contatos novos** no período, por *Original Traffic Source* (`hs_analytics_source`).
  - **Pipeline de pré-vendas** (890773148): negócios criados por etapa atual.
  - **Mãos levantadas (SQL)**: negócios do pré-vendas que **entraram** em "Lead qualificado (SQL)" no período (`hs_v2_date_entered_1343038270`), por dia e por *Canal de entrada*.
  - **WhatsApp**: contatos criados com *Canal de entrada* = WhatsApp **ou** com *GC | Mensagem do anúncio (WhatsApp)* preenchido.

## 3. Google Ads (para sair da cópia manual)

Conta 759-129-6003 (acesso com o login que já administra a conta).

1. **Developer token**: precisa de uma *conta de administrador (MCC)*. Em ads.google.com, crie uma MCC (grátis) e vincule a conta 759-129-6003 a ela. Na MCC: Ferramentas → **Central de API** → preencha o formulário. O token sai com acesso de teste; peça o **acesso Básico** (o Google analisa em alguns dias úteis). Com acesso de teste a API só lê contas de teste.
2. **Google Cloud**: em console.cloud.google.com, crie um projeto, ative a **Google Ads API** e crie uma credencial **OAuth (app para computador)**. Guarde *Client ID* e *Client secret*.
3. **Refresh token**: no OAuth Playground (developers.google.com/oauthplayground), engrenagem → "Use your own OAuth credentials" com o Client ID/secret, escopo `https://www.googleapis.com/auth/adwords`, autorize com o login da conta e troque o código pelo *refresh token*.
4. Segredos no GitHub:
   - `GADS_DEVELOPER_TOKEN`, `GADS_CLIENT_ID`, `GADS_CLIENT_SECRET`, `GADS_REFRESH_TOKEN`
   - `GADS_CUSTOMER_ID` = `7591296003`
   - `GADS_LOGIN_CUSTOMER_ID` = ID da MCC (sem traços)
5. Assim que esses segredos existirem, o script ignora a cópia manual e passa a trazer campanhas, palavras-chave, **termos de pesquisa** e investimento por dia.
   A versão da API está em `GADS_API_VERSION` (padrão `v21`); se o Google desativar essa versão, troque por uma atual.

> Esta parte não pôde ser testada ainda (não há developer token). Na primeira execução, confira a aba Integrações do painel.

## 4. GA4 — cliques no botão de WhatsApp do site

1. Google Cloud (mesmo projeto do passo 3): ative a **Google Analytics Data API**.
2. Crie uma **conta de serviço** e gere uma chave **JSON**.
3. No GA4 (propriedade 405901108): Administrador → Gerenciamento de acesso → adicione o e-mail da conta de serviço como **Leitor**.
4. Segredo `GA4_SERVICE_ACCOUNT_JSON` = o conteúdo inteiro do arquivo JSON.
5. **Confirmar o nome do evento.** O script conta o evento `clique_whatsapp`. Nas LPs ele vai para o `dataLayer`; não confirmei se chega ao GA4 com esse nome (o GA4 do site vem do Site Kit, não do GTM). Se o nome for outro, crie a variável `GA4_EVENTO_WHATSAPP`.

## 5. LinkedIn Ads

Hoje a aba mostra "sem números". Para ligar:

1. Regularizar o pagamento da conta de anúncios **511038871** (estava restrita em 31/10/2026) e ter campanhas rodando.
2. Em linkedin.com/developers, criar um app ligado à página da IMendes e pedir o produto **Advertising API** (o LinkedIn analisa o pedido).
3. Com o app aprovado, gerar um token com o escopo `r_ads_reporting` por um usuário com acesso à conta de anúncios.
4. Me avisar: eu escrevo a parte do LinkedIn no script (investimento, impressões, cliques, leads de Lead Gen Form e custo por lead) e o segredo será `LINKEDIN_ACCESS_TOKEN`.

O token do LinkedIn expira em 60 dias; o refresh token depende do tipo de aprovação do app.

## 6. WhatsApp

O número comercial não está conectado ao HubSpot (decisão de 07/11/2026), então não há API do WhatsApp aqui. O painel cruza três medidas que **não se somam**:

- **Conversas iniciadas** nos anúncios (Meta).
- **Contatos criados no HubSpot** pelo comercial com canal WhatsApp.
- **Cliques no botão** do site (GA4, depois do passo 4).

---

## Publicar no site

1. Crie a pasta no servidor, por exemplo `public_html/painel-mkt/`.
2. Proteja com senha: copie `hospedagem/.htaccess` para dentro dela e ajuste o caminho do `.htpasswd` (ou use "Privacidade de diretórios" do cPanel, que faz os dois).
3. Suba `index.html` e `logo-imendes-branca.png` para a pasta.
4. No GitHub, crie o repositório com o conteúdo desta pasta e cadastre os segredos:
   - Crie no cPanel (Arquivos → Contas FTP) um usuário restrito à pasta `public_html/painel-mkt`.
   - `DASH_UPLOAD_URL`: `ftp://br.jyn5040.com.br/dados.json` (com o usuário restrito, a raiz do FTP já é a pasta do painel). O envio usa FTP criptografado (TLS) obrigatório; o certificado do servidor vale para `br.jyn5040.com.br`, não para `grupoimendes.com.br`.
   - `DASH_UPLOAD_USER`: o usuário completo da conta FTP, como o cPanel mostra (ex.: `painel@grupoimendes.com.br`).
   - `DASH_UPLOAD_PASS`: a senha dessa conta FTP.
   - Opcionais, para manter o último dado bom quando um canal falhar: `DASH_JSON_URL` (`https://grupoimendes.com.br/painel-mkt/dados.json`), `DASH_SITE_USER`, `DASH_SITE_PASS` (o usuário e a senha da pasta).
5. Em Actions, rode "Atualizar painel de marketing" uma vez pelo botão **Run workflow** e abra `https://grupoimendes.com.br/painel-mkt/`.

### Repositório público (decidido em 13/11/2026)

O repositório é público para ter minutos ilimitados do GitHub Actions (a cada 10 min são cerca de 4.300 min/mês).
O código fica visível, mas os tokens (Secrets) e os números não: o `dados.json` só existe no site, atrás da senha.
O `google_ads_snapshot.json` (cópia manual do Reportei) está no `.gitignore` e não vai para o GitHub, então no site o Google Ads aparece como pendente até a API ser configurada.
Antes de cada `git add`, confira com `git status` que nenhum `.env`, `dados.json` ou snapshot entrou.

## Rodar no próprio computador (teste)

```bash
cd dashboard-marketing
export META_ACCESS_TOKEN=… HUBSPOT_TOKEN=…
python3 coletar_dados.py
python3 -m http.server 8765   # e abra http://127.0.0.1:8765
```

O `index.html` não abre com duplo clique (o navegador bloqueia a leitura do `dados.json` em `file://`); use um servidor como acima.
