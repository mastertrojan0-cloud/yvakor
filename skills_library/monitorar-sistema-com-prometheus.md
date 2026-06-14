<!-- skill: configurar-monitoramento-prometheus-grafana | tags: monitoramento, prometheus, grafana, devops, docker | status: nova -->
# Configurar monitoramento de servidores com Prometheus e Grafana via Docker

## Quando usar
Para configurar monitoramento de métricas de servidores, containers Docker ou aplicações web em produção, com dashboards visuais no Grafana. Ideal para ambientes pequenos/médios (até 50 hosts) gerenciados pela ACM Digital.

## Pré-requisitos
- Servidor Linux (Ubuntu 20.04+ ou Debian 11+) com Docker e Docker Compose instalados
- Portas 9090 (Prometheus), 3000 (Grafana) e 9100 (node_exporter) liberadas no firewall
- Acesso root ou sudo ao servidor
- Domínio ou IP público para acesso remoto (opcional)
- git instalado para clonar repositórios de dashboards (opcional)

## Procedimento

### 1. Criar estrutura de diretórios
```bash
mkdir -p /opt/monitoring/{prometheus,grafana}
cd /opt/monitoring
```

### 2. Criar arquivo de configuração do Prometheus
Crie `/opt/monitoring/prometheus/prometheus.yml`:
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
      - targets: ['{IP_DO_SERVIDOR}:9100']

  # Adicione mais jobs conforme necessário:
  # - job_name: 'docker_containers'
  #   static_configs:
  #     - targets: ['localhost:9323']  # cAdvisor
```

### 3. Criar docker-compose.yml
Crie `/opt/monitoring/docker-compose.yml`:
```yaml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    restart: unless-stopped
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana:/etc/grafana/provisioning
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD={SENHA_GRAFANA_ADMIN}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    ports:
      - "3000:3000"
    restart: unless-stopped
    networks:
      - monitoring
    depends_on:
      - prometheus

  node_exporter:
    image: prom/node-exporter:latest
    container_name: node_exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped
    networks:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### 4. Iniciar os serviços
```bash
cd /opt/monitoring
docker-compose up -d
```

### 5. Verificar se os serviços estão rodando
```bash
docker-compose ps
# Deve mostrar: prometheus, grafana, node_exporter como "Up"
```

### 6. Configurar fonte de dados no Grafana (automática)
Crie `/opt/monitoring/grafana/datasources/prometheus.yml`:
```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

### 7. Reiniciar o Grafana para aplicar a configuração
```bash
docker-compose restart grafana
```

### 8. Acessar interfaces
- **Prometheus**: http://{IP_DO_SERVIDOR}:9090
- **Grafana**: http://{IP_DO_SERVIDOR}:3000 (login: admin / {SENHA_GRAFANA_ADMIN})

### 9. Importar dashboard padrão (Node Exporter Full)
1. Acesse Grafana → "+" → "Import"
2. Digite o ID do dashboard: **1860** (Node Exporter Full)
3. Selecione a fonte de dados "Prometheus"
4. Clique em "Import"

### 10. Testar monitoramento
```bash
# Verificar métricas no Prometheus
curl http://localhost:9090/api/v1/query?query=up

# Verificar node_exporter
curl http://localhost:9100/metrics | head -20
```

## Erros conhecidos e soluções

### Erro: "container exit code 1" no Prometheus
**Causa**: Arquivo prometheus.yml mal formatado (YAML inválido)
**Solução**: Valide o YAML com:
```bash
python3 -c "import yaml; yaml.safe_load(open('/opt/monitoring/prometheus/prometheus.yml'))"
```

### Erro: Grafana não carrega dashboards
**Causa**: Permissões incorretas nos volumes
**Solução**:
```bash
chown -R 472:472 /opt/monitoring/grafana
docker-compose restart grafana
```

### Erro: node_exporter não coleta métricas de disco
**Causa**: Montagem incorreta do sistema de arquivos
**Solução**: Verifique se o container tem acesso a `/proc` e `/sys`:
```bash
docker exec node_exporter ls /host/proc/stat
```

### Erro: Porta 9090 já em uso
**Causa**: Outro serviço usando a porta
**Solução**: Altere a porta no docker-compose.yml:
```yaml
ports:
  - "9091:9090"  # Mapeia para porta 9091 externa
```

### Erro: "Permission denied" ao criar diretórios
**Causa**: Sem permissão sudo
**Solução**: Use `sudo` ou execute como root:
```bash
sudo mkdir -p /opt/monitoring/{prometheus,grafana}
```

## Exemplo aplicado ao contexto do usuário

### Cenário: Monitorar servidor de produção da ACM Digital
```bash
# 1. Acessar servidor via SSH
ssh antonio@servidor.acmdigital.com.br

# 2. Criar estrutura
sudo mkdir -p /opt/monitoring/{prometheus,grafana}
cd /opt/monitoring

# 3. Configurar prometheus.yml com targets específicos
cat > prometheus/prometheus.yml << 'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node_exporter'
    static_configs:
      - targets: ['192.168.1.100:9100']

  - job_name: 'docker_containers'
    static_configs:
      - targets: ['localhost:9323']
EOF

# 4. Criar docker-compose.yml com senha segura
# (substitua {SENHA_GRAFANA_ADMIN} por senha forte)

# 5. Iniciar
docker-compose up -d

# 6. Verificar
docker-compose ps
curl http://localhost:9090/api/v1/query?query=up

# 7. Acessar Grafana e importar dashboard 1860
# URL: http://192.168.1.100:3000
# Login: admin / {senha definida}
```

### Verificação rápida de saúde do sistema
```bash
# Script de verificação
#!/bin/bash
echo "=== Status do Monitoramento ==="
docker-compose ps --format "table {{.Name}}\t{{.Status}}"
echo ""
echo "=== Métricas do Prometheus ==="
curl -s http://localhost:9090/api/v1/query?query=up | python3 -m json.tool
echo ""
echo "=== Uso de Disco ==="
df -h /opt/monitoring
```

### Notas importantes para o contexto ACM Digital
- Para clientes que precisam de monitoramento 24/7, configure alertas no Grafana (Alerting → Notification channels)
- Para ambientes com múltiplos servidores, use service discovery (consul, dns_sd_configs) em vez de targets estáticos
- Backup dos volumes: `docker run --rm -v prometheus_data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus_backup_$(date +%Y%m%d).tar.gz -C /data .`
- Para monitorar aplicações web específicas, adicione exporters customizados (ex: nginx_exporter, postgres_exporter)
