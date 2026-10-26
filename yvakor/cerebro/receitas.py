"""
YVAKOR — Receitas executáveis (skills com contrato)

Uma skill pode conter, além da prosa, um bloco YAML com passos de ferramentas:

    ## Receita
    ```yaml
    aprovada: true
    gatilhos: ["status do disco", "espaco livre"]
    parametros:
      unidade: "([A-Za-z]):"
    passos:
      - ferramenta: executar_shell
        args: {comando: "dir {{unidade}}:\\\\"}
    ```

Regras de segurança:
  • só executa receita com `aprovada: true` (você revisou e liberou);
  • `simular=True` mostra os passos sem executar;
  • ferramenta inexistente/argumento inválido aborta antes de qualquer ação;
  • placeholders `{{param}}` e `{{passoN.campo}}` são substituídos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Receita:
    nome: str
    caminho: str
    aprovada: bool = False
    gatilhos: list[str] = field(default_factory=list)
    parametros: dict = field(default_factory=dict)
    passos: list[dict] = field(default_factory=list)
    descricao: str = ""


def _bloco_yaml(texto: str) -> str:
    m = re.search(r"##+\s*Receita\b(.*?)(?=\n##+\s|\Z)", texto, re.S | re.I)
    if not m:
        return ""
    corpo = m.group(1)
    m2 = re.search(r"```(?:yaml|yml)?\s*(.*?)```", corpo, re.S)
    return (m2.group(1) if m2 else corpo).strip()


def carregar_de_texto(nome: str, texto: str, caminho: str = "") -> Receita | None:
    bruto = _bloco_yaml(texto)
    if not bruto:
        return None
    try:
        dados = yaml.safe_load(bruto) or {}
    except Exception:
        return None
    if not isinstance(dados, dict) or not dados.get("passos"):
        return None
    return Receita(
        nome=nome,
        caminho=caminho,
        aprovada=bool(dados.get("aprovada", False)),
        gatilhos=[str(g) for g in (dados.get("gatilhos") or [])],
        parametros=dict(dados.get("parametros") or {}),
        passos=[p for p in dados.get("passos") or [] if isinstance(p, dict)],
        descricao=str(dados.get("descricao") or ""),
    )


def carregar_todas(pasta: Path) -> list[Receita]:
    receitas = []
    for arquivo in sorted(Path(pasta).glob("*.md")):
        try:
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        r = carregar_de_texto(arquivo.stem, texto, str(arquivo))
        if r:
            receitas.append(r)
    return receitas


class ExecutorReceitas:
    def __init__(self, registry):
        self.registry = registry

    # ------------------------------------------------------------------ #
    def validar(self, receita: Receita) -> list[str]:
        erros = []
        if not receita.aprovada:
            erros.append("receita não aprovada (aprovada: false)")
        if not receita.passos:
            erros.append("sem passos")
        for i, passo in enumerate(receita.passos, 1):
            ferramenta = str(passo.get("ferramenta") or "")
            if not ferramenta:
                erros.append(f"passo {i}: sem 'ferramenta'")
            elif ferramenta not in self.registry.tools:
                erros.append(f"passo {i}: ferramenta desconhecida '{ferramenta}'")
            elif not isinstance(passo.get("args", {}), dict):
                erros.append(f"passo {i}: 'args' deve ser objeto")
        return erros

    # ------------------------------------------------------------------ #
    def parametros(self, receita: Receita, texto: str) -> dict:
        achados = {}
        for nome, padrao in (receita.parametros or {}).items():
            try:
                m = re.search(str(padrao), texto or "", re.I)
                achados[nome] = m.group(1) if m and m.groups() else (
                    m.group(0) if m else "")
            except re.error:
                achados[nome] = ""
        return achados

    @staticmethod
    def _substituir(valor, variaveis: dict):
        if isinstance(valor, str):
            def troca(m):
                chave = m.group(1).strip()
                atual = variaveis
                for parte in chave.split("."):
                    if isinstance(atual, dict) and parte in atual:
                        atual = atual[parte]
                    else:
                        return m.group(0)
                if isinstance(atual, (dict, list)):
                    return json.dumps(atual, ensure_ascii=False)
                return str(atual)
            return re.sub(r"\{\{\s*([^}]+)\s*\}\}", troca, valor)
        if isinstance(valor, dict):
            return {k: ExecutorReceitas._substituir(v, variaveis)
                    for k, v in valor.items()}
        if isinstance(valor, list):
            return [ExecutorReceitas._substituir(v, variaveis) for v in valor]
        return valor

    def executar(self, receita: Receita, texto: str = "",
                 simular: bool = False) -> dict:
        erros = self.validar(receita)
        if erros:
            return {"ok": False, "erros": erros, "executado": False}
        variaveis = self.parametros(receita, texto)
        plano = []
        resultados = []
        for i, passo in enumerate(receita.passos, 1):
            args = self._substituir(passo.get("args") or {}, variaveis)
            plano.append({"passo": i, "ferramenta": passo["ferramenta"],
                          "args": args})
        if simular:
            return {"ok": True, "simulado": True, "receita": receita.nome,
                    "parametros": variaveis, "plano": plano}

        for i, passo in enumerate(receita.passos, 1):
            ferramenta = str(passo["ferramenta"])
            try:
                args = self._substituir(passo.get("args") or {},
                                        {**variaveis,
                                         **{f"passo{n}": resultados[n - 1]
                                            for n in range(1, i)}})
                resultado = self.registry.run(ferramenta, **args)
            except Exception as exc:
                return {"ok": False, "executado": True, "passo": i,
                        "erro": f"{type(exc).__name__}: {exc}",
                        "resultados": resultados}
            resultados.append(resultado)
            if isinstance(resultado, dict) and resultado.get("ok") is False:
                return {"ok": False, "executado": True, "passo": i,
                        "erro": resultado.get("erro") or resultado.get("error"),
                        "resultados": resultados}
        return {"ok": True, "executado": True, "receita": receita.nome,
                "parametros": variaveis, "passos": len(resultados),
                "resultados": resultados}
