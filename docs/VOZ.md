# YVAKOR — Voz (falar e ouvir)

Dois motores, ambos locais quando possível:

| Etapa | Motor | Observação |
|---|---|---|
| Ouvir (STT) | **Vosk** pequeno pt-BR | offline, CPU, modelo ~31 MB baixado 1× |
| Falar (TTS) | **edge-tts** (neural) | masculina `pt-BR-AntonioNeural`; cai para SAPI se falhar |
| Falar (TTS) | **SAPI** (Windows) | offline, prioriza voz masculina pt-BR instalada |

---

## 1. Usar

```bash
python -m yvakor.voz                 # conversa por voz (diz "yvakor" para acordar)
python -m yvakor.voz --sem-ativacao  # fala direto, sem palavra-chave
python -m yvakor.voz --uma           # uma pergunta e sai
```

No chat/interface: botão **🎙** (microfone) e **🔊** (falar respostas).
No app nativo, o botão **🔊 VOZ** no topo ativa/desativa a fala do agente e a
preferência fica salva no núcleo.
O navegador usa a Web Speech API quando existe; se não, grava e manda para o
Vosk do servidor.

Como ferramenta, o agente pode usar:

- `voz_falar("texto")` — fala no alto-falante da máquina;
- `voz_ouvir(segundos)` — escuta o microfone (precisa de hardware);
- `voz_transcrever("audio.mp3")` — transcreve arquivo;
- `voz_status()` — modelo, microfone e vozes.

---

## 2. Sem microfone

Se a máquina não tem entrada de áudio (foi o caso do ambiente de
desenvolvimento), `ouvir()` devolve erro explicando as alternativas — o resto
continua funcionando:

1. grave no celular e mande o arquivo → `voz_transcrever`;
2. use o microfone da interface web (o áudio vem do navegador);
3. use TTS normalmente (saída de áudio existe em qualquer PC).

---

## 3. Configuração

```yaml
voz:
  idioma: "pt-BR"
  stt: "auto"                      # auto | vosk
  modelo_vosk: "vosk-model-small-pt-0.3"
  tts: "auto"                      # auto | edge | sapi
  voz_edge: "pt-BR-AntonioNeural"
  voz_sapi: ""                     # vazio = melhor voz masculina pt-BR
  velocidade: 0
  tom: "+0Hz"
  escuta_segundos: 7
  silencio_rms: 0.012              # sensibilidade do VAD
  silencio_fim_ms: 900
  palavra_ativacao: "yvakor"
```

A palavra de ativação é tolerante a erros do reconhecedor: "eva coruja",
"ivacor" e "yvacor" também acordam o agente.

---

## 4. Dicas

- **Nome inventado é reconhecido errado.** "YVAKOR" costuma sair como "eva
  coruja" no modelo pequeno; use os aliases ou um modelo maior
  (`vosk-model-pt-fb-v0.1.1-20220516_2113`, ~1,5 GB) para melhorar.
- **Ruído:** ajuste `silencio_rms` (mais alto = menos sensível).
- **Respostas longas:** o assistente fala só o começo (limite ~700 caracteres,
  corte em fim de frase) para não virar monólogo.
- **Privacidade:** Vosk roda local; nenhum áudio sai da máquina. O edge-tts
  envia apenas o texto a ser falado.

---

## 5. Problemas comuns

| Sintoma | Solução |
|---|---|
| "nenhum microfone detectado" | use arquivo/navegador (seção 2) |
| Modelo não baixa | verifique internet; o zip fica em `data/vosk/` |
| Voz robótica | instale vozes neurais do Windows ou use edge-tts |
| Não acorda com "yvakor" | diga "yvakor" mais devagar ou ajuste `aliases_ativacao` |
| Áudio não toca | verifique saída padrão do Windows; ffplay é o fallback |
