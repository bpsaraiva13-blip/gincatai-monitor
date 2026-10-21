# Monitor XV Gincataí → WhatsApp / Telegram

Verifica o site da Alquimia (API pública do WordPress) e avisa quando:

- sai **tarefa nova** (com título, setor, link e PDF);
- aparece **arquivo novo** na biblioteca de mídia (às vezes sobe antes do post);
- a página da gincana muda (**Avisos / Downloads**).

Tudo gratuito: **GitHub Actions** (execução) + **cron-job.org** (disparo a cada 1 min) + **Green API** (WhatsApp) e/ou **Telegram**.
Configure um ou os dois canais: o script envia para todos que estiverem configurados.

---

## 1A. WhatsApp com Green API (plano Developer, grátis)

O plano grátis permite **3 chats** (contatos ou grupos) e envio ilimitado de mensagens.
A Green API funciona conectando um WhatsApp por QR code (como o WhatsApp Web).

> ⚠️ **Use um número diferente do seu.** A mensagem sai *do* WhatsApp conectado. Se você conectar o seu próprio número, ela aparece como enviada por você e **seu celular não toca**.
> Use um chip reserva, o número de outra pessoa da equipe ou um WhatsApp Business em outro número.
> Por ser API não oficial, existe um risco pequeno de bloqueio do número conectado. Mais um motivo para não usar o seu principal.

1. Crie conta em <https://console.green-api.com> → **Create instance** → plano **Developer**.
2. Escaneie o QR code com o WhatsApp do **número reserva** (Aparelhos conectados → Conectar aparelho).
3. Anote, no console da instância:
   - `idInstance` → secret `GREEN_API_INSTANCE`
   - `apiTokenInstance` → secret `GREEN_API_TOKEN`
   - `apiUrl` (ex.: `https://7105.api.greenapi.com`) → secret `GREEN_API_URL`
4. Defina quem recebe → secret `GREEN_API_CHATS` (separados por vírgula, máx. 3):
   - contato: só o número com DDI e DDD, ex.: `5551999999999`
   - grupo: o id do grupo, ex.: `120363012345678901@g.us`
     (adicione o número reserva ao grupo da equipe; o id aparece no console, em *Journals → incoming*, depois que alguém mandar uma mensagem no grupo, ou via método `getContacts`).
5. Teste rápido pelo terminal:
   ```bash
   curl -X POST "$APIURL/waInstance$ID/sendMessage/$TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"chatId":"5551999999999@c.us","message":"teste"}'
   ```

## 1B. Telegram (alternativa, 100% grátis e sem limite)

1. No Telegram, fale com **@BotFather** → `/newbot` → guarde o token → secret `TELEGRAM_BOT_TOKEN`.
2. Mande qualquer mensagem para o seu bot (ou adicione o bot no grupo da equipe e mande uma mensagem lá).
3. Abra `https://api.telegram.org/bot<TOKEN>/getUpdates` e copie o `chat.id` → secret `TELEGRAM_CHAT_IDS`
   (vários: `123456789,-100987654321`; grupos começam com `-`).

## 2. Criar o repositório no GitHub

1. Crie um repositório **público** (Actions é ilimitado em repo público; em privado são 2.000 min/mês, que acabam rápido rodando a cada minuto). Nenhum segredo fica no código.
2. Suba os arquivos:
   ```
   monitor.py
   requirements.txt
   .github/workflows/monitor.yml
   ```
3. Instância, URL e grupo já estão no `.github/workflows/monitor.yml`. Falta só o token:
   **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `GREEN_API_TOKEN`
   - Valor: o `apiTokenInstance` do console da Green API
4. **Actions** → *Monitor Gincataí* → **Run workflow** → marque **"Enviar mensagem de teste"** → Run.
   A mensagem 🔔 de teste deve chegar no grupo.

## Como roda (a cada ~1 minuto, sem serviço externo)

Cada execução do workflow fica ~55 min em loop, verificando o site a cada 60 s.
O `schedule` (a cada 15 min) mantém sempre uma próxima execução **na fila** graças ao
`concurrency`: quando uma termina, a seguinte começa imediatamente.
O aviso chega em ~1 min após a publicação.

Ajustes no `.github/workflows/monitor.yml`: `INTERVALO` (segundos entre verificações) e `DURACAO`.

Para desligar depois da gincana: **Actions → Monitor Gincataí → ⋯ → Disable workflow**.

## Rodar localmente / numa VM (opcional)

```bash
pip install -r requirements.txt

# teste sem enviar nada
DRY_RUN=1 python monitor.py

# loop contínuo a cada 30 s (ex.: no seu PC durante a gincana, 14–15/11)
export GREEN_API_INSTANCE=... GREEN_API_TOKEN=... GREEN_API_URL=... GREEN_API_CHATS=5551999999999
RUN_FOREVER=1 INTERVAL=30 python monitor.py
```

Para resetar (re-registrar tudo sem avisar), apague o `state.json`.

## Observações

- Posts **agendados** no WordPress não são visíveis publicamente: o aviso sai no momento em que a tarefa é publicada.
- O aviso de "arquivo novo" só funciona para arquivos que não estão vinculados a um post ainda não publicado.
- Desligue o cronjob depois de 15/11 (e/ou desabilite o workflow) para não ficar rodando à toa.
- Fique de olho também nos grupos oficiais de WhatsApp: o regulamento diz que tarefas podem sair por lá ou entregues em mãos.
- O CallMeBot continua suportado (`CALLMEBOT_RECIPIENTS="5551999999999:APIKEY"`), caso abram vagas.
