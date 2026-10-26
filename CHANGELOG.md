# Changelog

## 0.8.0 — 2026-10-23

### Produto
- Versionamento central (`config/version.json`) e sincronização da extensão.
- Empacotamento de release (`scripts/build_release.py`) com SHA-256.
- Diagnóstico de instalação (`scripts/doctor.py`, 16 checagens).
- `pyproject.toml`, dependências de PDF/OCR/VLC e documentação de produto.

### Agente
- Respostas curtas por padrão: até 3 frases no simples, sem cumprimento,
  repetição da pergunta nem ofertas tipo “se quiser...”;
  entregas mostram resumo curto + link.
- Cérebro só responde direto quando o pedido é explicitamente de memória;
  perguntas gerais vão para o modelo, evitando notas irrelevantes.
- Visão local com Ollama `moondream` (1,7 GB) para descrever telas/fotos;
  imagem reduzida para 384 px e OCR como complemento.
- Motor de contexto: seleção por relevância da página (até 9 mil
  caracteres), cabeçalhos, descrição e seleção do usuário; respostas
  fundamentadas com citação da seção.
- Extensão captura a tela automaticamente quando o texto é curto ou o pedido
  é visual; o núcleo faz OCR e analisa sem pedir print ao usuário.
- Entregáveis reais: relatórios PDF/HTML/DOCX, planilhas XLSX/CSV e fotos
  com licenças abertas (Openverse/Wikimedia/Pexels), exibidos no chat.
- Ferramenta de fotos ampliada: Pexels (opcional), Openverse e Wikimedia em
  todas as licenças, com atribuição; fallback gera imagem quando não há foto.
- Atalhos determinísticos para relatório, gráfico, foto e imagem gerada,
  com teto de 180 s por execução do agente.
- Autonomia: prompt de execução sem confirmações desnecessárias, fallback de
  PDF→HTML, XLSX→CSV, imagem→foto real e retomada automática de tarefas
  cowork interrompidas ao reiniciar.
- Respostas de entrega citam automaticamente todos os artefatos gerados.
- Ferramentas de entrega roteadas com prioridade e atalhos diretos para
  gráfico e foto.
- Respostas mais completas em análise/pesquisa/entrega; conversa simples
  continua curta.
- Pesquisa profunda com múltiplas fontes, paralelismo e citações.
- OCR (Windows) e leitura de PDF (nativo/digitalizado).
- Agenda persistente com repetição diária/semanal e API.
- Subagentes paralelos de análise.
- Avaliação automática de qualidade (1–5) em segundo plano.
- MCP: cliente de ferramentas externas.
- Chrome real via CDP, com perfil dedicado e sem flags de automação.

### Interface
- Corrigida falha de continuidade: se o painel fechasse, o agente caía no
  Playwright e dizia “Chrome fechou”. Agora o service worker executa toda a
  ponte (abrir, ver, clicar, preencher, abas) sem depender do painel.
- Comandos aguardam a extensão acordar (service worker/alarmes até ~30 s)
  em vez de falhar na hora; janela de disponibilidade ampliada.
- Interação visível na página: cursor animado, ripple de clique e digitação.
  caractere por caractere.
- `navegador_ver`/extração agora enxergam shadow DOM (YouTube etc.): texto
  visível e elementos clicáveis com refs, ignorando `<script>`/`<style>`.
  Clique/preenchimento localizam o elemento por ref dentro de shadow roots.
- Desempenho: snapshot compacto (60 elementos, ~3,5 KB, ~0,14 s), observação
  de ferramenta limitada a 2 KB e orçamento de contexto reduzido a 5 KB.
- Abas: `navegador_abrir` reaproveita uma aba de controle (navega nela) em vez
  de abrir várias; `navegador_nova_aba` cria uma nova explicitamente.
- Ao abrir/navegar, aguarda a página carregar; `navegador_ver` tenta de novo
  (até 5×) se título/conteúdo vierem em branco.
- **Toda** a navegação do agente (abrir, ir, ler, clicar, preencher, rolar,
  abas) usa por padrão a janela do Chrome da extensão; `navegador='edge'`
  ou pedido explícito usa outro.
- Pedidos compostos (“abre e pesquisa…”) vão para o agente, não param no
  atalho de abertura; modo navegador exige verificação final.
- Painel do Chrome simplificado: um chat único, sem abas Cowork/Code;
  contexto da página, processo inline e voz neural.
- Extensão lê a aba ativa (até 12 mil caracteres) automaticamente, atualiza ao
  trocar de aba e não usa botões de contexto.
- Voz masculina amigável/profissional: `pt-BR-AntonioNeural`, tom +0 Hz,
  cadência natural; SAPI prioriza voz masculina.
- Botão **🔊 VOZ** no app nativo e no painel do Chrome para ativar/desativar
  a fala; preferência persistida no núcleo.
- Extensão Chrome: side panel compacto, voz, badge de atualização.
- Painéis ao vivo de navegador e câmera dentro da conversa.
- Upload de imagens, vídeos e documentos no chat.
- Fontes Sora/Unbounded e paleta do HTML.

### Correções
- Sessões isoladas, corrida de mensagens e histórico enxuto.
- Inicialização não bloqueante, single-instance e supervisor com ping.
- Absorção/avaliação assíncronas para não travar respostas.
- Conversa contínua: continuações não caem mais em notas irrelevantes.
