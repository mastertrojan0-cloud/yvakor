# Prompts de Absorção Automática de Conhecimento

Estes prompts fazem o YVAKOR **aprender sozinho** a partir da IA principal
(DeepSeek V4). A cada interação, a IA principal não só responde — ela é
"ordenhada": fatos, procedimentos e exemplos são extraídos automaticamente
e gravados nas memórias do YVAKOR. Com o tempo, o conhecimento migra da
API externa para os arquivos locais do agente.

| Arquivo | Quando roda | Grava em |
|---|---|---|
| 01_extrator_de_fatos.md | após CADA resposta | memória semântica |
| 02_destilador_de_skill.md | quando reflexão detecta padrão | skills_library/ |
| 03_professor_dataset.md | em lote (madrugada/manual) | data/dataset/ (fine-tuning futuro) |
| 04_autoavaliacao.md | após tarefas relevantes | memória episódica |
| 05_consolidador_memoria.md | semanal | memória semântica (limpeza) |

Pipeline implementado em `yvakor/learning/absorber.py`.
Custo: cada extração usa o tipo de tarefa "classificacao" — roteável para
o modelo LOCAL assim que o Ollama estiver ativo (custo zero).
