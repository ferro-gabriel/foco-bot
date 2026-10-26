# Bot da Foco Radical 📸

Roda sozinho no GitHub (grátis, na nuvem), 24h por dia, e te manda no Telegram:

| Quando | O quê |
|---|---|
| A cada 3 min | 💰 **Venda nova**, um aviso por pedido: fotos vendidas **sem marca d'água**, evento, Premium/Alta/vídeo, hora do pagamento, Pix/cartão, sua parte, quanto o cliente pagou, horário em que as fotos foram tiradas, total do evento × média dos fotógrafos e quanto você já vendeu hoje |
| 7h | ☀️ Melhores eventos abertos + 🆕 eventos novos + ⏰ cadastros fechando |
| 18h | 🆕 eventos novos, vagas que abriram, listas de espera que abriram |
| 9h | 📊 Relatório diário + relatório detalhado da **Vila Germânica** (horários que mais vendem, Premium x Alta, você x média dos fotógrafos, fotos vendidas) |
| Segunda 9h | 🗓 Resumo da semana + você × média dos fotógrafos em cada evento |

## Comandos no Telegram (resposta na hora)
`/relatorio` · `/vendas` · `/agenda` · `/eventos` · `/semana` · `/ajuda`

Os eventos recomendados já vêm comparados com a sua agenda: o que você já está inscrito ou na lista de espera não aparece de novo, e eventos no mesmo dia de um compromisso seu vêm com ⚠️. Quando você é aprovado numa lista de espera, chega 🎉. No `/agenda`, cada evento confirmado vem com a sua classificação nele (🏆 27º de 63 fotógrafos), a mesma do Painel do Evento.

## De onde vêm os dados
O painel da Foco foi refeito em out/2026: vendas, pedidos e fotos vendidas vêm da API nova do painel (`/next-api/...`, a mesma que as telas usam); eventos e agenda continuam nas páginas antigas. Se o painel mudar de novo e uma leitura vier vazia, o bot avisa no Telegram em vez de ficar quieto.

## Privacidade
O código é público; senhas ficam nos *Secrets* do GitHub e a memória do bot (vendas, agenda) fica em `state/state.enc`, criptografada com a chave `STATE_KEY`.

## Filtros (edite em `foco/config.py`)
- **SC**: tudo até 300 km de Blumenau
- **PR e RS**: só eventos grandes (8+ fotógrafos ou lista de espera)
- Acima de 300 km: só eventos enormes (20+ fotógrafos)
- Sempre avisa sobre: Oktoberfest, Vila Germânica, Sommerfest, Marejada, Fenarreco, Schützenfest, Fenachopp

## Nota de 0 a 10
Tipo de evento (calibrado com suas vendas de 2026: corridas e festas vendem mais) + tamanho (nº de fotógrafos) + Parceria Foco + distância + fim de semana + venda Premium.

## Configuração (uma vez só)
Em **Settings → Secrets and variables → Actions → New repository secret** crie:

| Nome | Valor |
|---|---|
| `FOCO_USER` | seu login do FocoMarket |
| `FOCO_PASSWORD` | sua senha do FocoMarket |
| `TELEGRAM_TOKEN` | token que o @BotFather te deu |
| `STATE_KEY` | chave da memória criptografada (já criada; cópia local em `.env`) |

Depois mande um "oi" para o seu bot no Telegram e rode **Actions → foco-bot → Run workflow → test**.
O chat é descoberto sozinho.

## Rodar no Mac (opcional)
```bash
pip3 install -r requirements.txt
FOCO_USER=... FOCO_PASSWORD=... python3 main.py test      # testa o login
FOCO_USER=... FOCO_PASSWORD=... DRY_RUN=1 python3 main.py events   # mostra no terminal em vez do Telegram
python3 -m unittest discover tests                          # testes
```

## Trocar o evento em foco
Em `main.py`, `FOCUS_EVENTS = {"269944": "Vila Germânica – Oktoberfest 2026"}`. O número é o ID do evento no painel (aparece no relatório "Vendas por Evento").
