<!-- skill: criar-dashboard-monitoramento-grafana | tags: grafana, prometheus, monitoramento, infraestrutura, métricas | status: nova -->
# Criar dashboard de monitoramento com Grafana e Prometheus
## Quando usar
Quando precisar visualizar métricas de sistemas, servidores ou aplicações em tempo real para relatórios, tomada de decisão ou diagnóstico de problemas. Ideal para projetos ACM Digital que exigem monitoramento de serviços web, APIs ou servidores.

## Pré-requisitos
- Docker e Docker Compose instalados no servidor ou máquina local.
- Acesso ao terminal com permissão para executar containers.
- Portas 3000 (Grafana) e 9090 (Prometheus) livres.
- Conhecimento básico de métricas (CPU, memória, disco, rede).

## Procedimento
1. **Criar diretório do projeto**
   ```bash
   mkdir -p ~/monitoramento && cd ~/monitoramento
   ```

2. **Criar arquivo `docker-compose.yml`**
   ```yaml
   version: '3.8'
   services:
     prometheus:
       image: prom/prometheus:latest
       container_name: prometheus
       volumes:
         - ./prometheus.yml:/etc/prometheus/prometheus.yml
         - prometheus_data:/prometheus
       ports:
         - "9090:9090"
       restart: unless-stopped

     grafana:
       image: grafana/grafana:latest
       container_name: grafana
       ports:
         - "3000:3000"
       environment:
         - GF_SECURITY_ADMIN_USER=admin
         - GF_SECURITY_ADMIN_PASSWORD={senha_grafana}
       volumes:
         - grafana_data:/var/lib/grafana
       restart: unless-stopped

   volumes:
     prometheus_data:
     grafana_data:
   ```

3. **Criar arquivo `prometheus.yml`**
   ```yaml
   global:
     scrape_interval: 15s
     evaluation_interval: 15s

   scrape_configs:
     - job_name: 'prometheus'
       static_configs:
         - targets: ['localhost:9090']

     - job_name: 'node_exporter'
       static_configs:
         - targets: ['{ip_servidor}:9100']
   ```
   Substitua `{ip_servidor}` pelo IP do servidor que deseja monitorar (ex: `192.168.1.100`). Para monitorar a própria máquina, use `localhost`.

4. **Iniciar os containers**
   ```bash
   docker-compose up -d
   ```

5. **Verificar se os serviços estão rodando**
   ```bash
   docker ps
   ```
   Devem aparecer os containers `prometheus` e `grafana`.

6. **Acessar o Grafana**
   - Abra o navegador em `http://{ip_servidor}:3000`
   - Login: `admin` / senha definida no passo 2

7. **Adicionar Prometheus como fonte de dados no Grafana**
   - No menu lateral, vá em **Configuration > Data Sources > Add data source**
   - Selecione **Prometheus**
   - Em **URL**, digite `http://prometheus:9090`
   - Clique em **Save & Test** (deve aparecer "Data source is working")

8. **Criar um dashboard básico**
   - No menu lateral, vá em **Create > Dashboard > Add new panel**
   - Na aba **Query**, insira a métrica desejada (ex: `up` para verificar se os targets estão ativos)
   - Ajuste o título e a visualização (ex: gráfico de séries temporais)
   - Clique em **Apply** e depois no ícone de disquete para salvar o dashboard

9. **Adicionar métricas comuns de sistema (opcional)**
   - Se tiver um `node_exporter` rodando no servidor alvo, use métricas como:
     - `node_cpu_seconds_total` (CPU)
     - `node_memory_MemAvailable_bytes` (memória)
     - `node_filesystem_avail_bytes` (disco)
   - Exemplo de query para uso de CPU:
     ```
     100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
     ```

## Erros conhecidos e soluções
| Erro | Causa | Solução |
|------|-------|---------|
| Grafana não acessível | Porta 3000 bloqueada | Verifique firewall: `sudo ufw allow 3000` |
| Prometheus não coleta dados | `prometheus.yml` mal formatado | Valide YAML em https://yamlchecker.com |
| "Data source is working" falha | Nome do container errado | Use `http://prometheus:9090` (nome do serviço no docker-compose) |
| Containers não sobem | Porta ocupada | Mude a porta no docker-compose (ex: 3001:3000) |
| node_exporter não aparece | IP errado ou serviço não instalado | Instale node_exporter no servidor alvo: `wget ... && ./node_exporter` |

## Exemplo aplicado ao contexto do usuário
**Cenário:** Antonio precisa monitorar um servidor web da ACM Digital que hospeda um chatbot em Node.js.

**Passos adaptados:**
1. No servidor do chatbot (IP `10.0.0.50`), instale o node_exporter:
   ```bash
   wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-1.6.0.linux-amd64.tar.gz
   tar xvf node_exporter-*.tar.gz
   cd node_exporter-*/
   ./node_exporter &
   ```
2. No `prometheus.yml`, adicione o target:
   ```yaml
   - job_name: 'chatbot_server'
     static_configs:
       - targets: ['10.0.0.50:9100']
   ```
3. Reinicie o Prometheus: `docker restart prometheus`
4. No Grafana, crie um dashboard com:
   - Painel de CPU do servidor
   - Painel de memória disponível
   - Painel de latência da aplicação (se expor métricas customizadas)
5. Configure alertas no Grafana para enviar e-mail ou notificação Slack se CPU > 80% por 5 minutos.
