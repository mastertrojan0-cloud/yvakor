<!-- skill: Status de disco (receita) | tags: disco, espaco, receita -->
# Status de disco (receita)

Exemplo de **receita executável**: o cérebro roda os passos abaixo sem IA.
Revise e mantenha `aprovada: true` para permitir execução.

## Quando usar

Quando o usuário perguntar pelo espaço livre de uma unidade (ex.: "status do
disco C:").

## Receita

```yaml
aprovada: true
descricao: Mostra espaço livre e total de uma unidade do Windows.
gatilhos:
  - "status do disco"
  - "espaco livre"
  - "espaço em disco"
parametros:
  unidade: "([A-Za-z]):"
passos:
  - ferramenta: executar_shell
    args:
      comando: 'powershell -NoProfile -Command "Get-PSDrive {{unidade}} | Select-Object Used,Free | Format-List"'
```

## Observações

- Sem `unidade` no pedido, o placeholder fica literal e o comando falha: peça
  "disco C:" para o agente.
