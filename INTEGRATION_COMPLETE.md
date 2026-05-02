# Integración Completa del Sistema

## ✅ Cambios Realizados

### 1. GitHub Action ([.github/workflows/update-opensearch-on-issue-change.yml](.github/workflows/update-opensearch-on-issue-change.yml))
- Detecta cuando una issue se cierra, reabre, o cambia de asignado
- Actualiza OpenSearch automáticamente:
  - Campo `status` → `closed` o `open`
  - Campo `assignee` → usuario asignado (excluyendo wazuh-community)
  - Campo `closed_at` → timestamp cuando se cierra

### 2. Auditor ([tools/auditor/auditor.py](tools/auditor/auditor.py))
- Modificado para ejecutarse en bucle infinito
- Se ejecuta cada 5 minutos automáticamente
- Cuenta tickets y rellena quotas en `community-quota-v1`

### 3. Assigner ([tools/assigner/assigner.py](tools/assigner/assigner.py))
- Reescrito completamente como librería
- Clase `IssueAssigner` con métodos:
  - `assign_issue(issue_number)` - Asigna automáticamente al usuario con menos tickets
  - `get_available_users()` - Obtiene usuarios con cuota disponible (< 2 tickets)
  - `_update_user_quota()` - Incrementa/decrementa quota en OpenSearch
- Consulta `community-quota-v1` para saber quién tiene cuota
- Actualiza quota (+1) cuando asigna
- Actualiza `assignee` en `tickets-raw-v1.0`

### 4. Collector ([tools/collector/](tools/collector/))
**Archivos modificados:**
- [discord_gw.py](tools/collector/discord_gw.py)
- [slack_gw_v2.py](tools/collector/slack_gw_v2.py)

**Cambios:**
- Importa `IssueAssigner`
- Después de crear un ticket en GitHub, llama automáticamente a `assigner.assign_issue()`
- Si la asignación falla, continúa (no bloquea la creación del ticket)

## 🔄 Flujo Completo

```
1. Mensaje nuevo en Discord/Slack
   ↓
2. collector/main.py (discord_gw.py o slack_gw_v2.py)
   ↓
3. Crea issue en GitHub
   ↓
4. Indexa en tickets-raw-v1.0
   ↓
5. Llama a assigner.assign_issue(issue_number)
   ├─ Consulta community-quota-v1
   ├─ Encuentra usuario con < 2 tickets
   ├─ Asigna en GitHub
   ├─ Actualiza quota (+1)
   └─ Actualiza assignee en tickets-raw-v1.0
```

**Proceso separado:**
```
auditor.py (cada 5 minutos)
   ├─ Cuenta tickets por usuario
   └─ Rellena/actualiza community-quota-v1
```

## 📊 Índices OpenSearch

### tickets-raw-v1.0
- Source of truth para tickets
- Campos: `github_issue_number`, `assignee`, `status`, `closed_at`

### community-quota-v1
- Tracking de quotas por usuario
- Campos: `github_username`, `ticket_count`, `year`, `week`

## 🚀 Ejecución

### Proceso 1: Collector
```bash
cd tools/collector
python main.py
```

### Proceso 2: Auditor
```bash
cd tools/auditor
python auditor.py
```

## ⚙️ Configuración necesaria

### Secrets de GitHub (para el Action):
- `OPENSEARCH_PASSWORD`

### Tokens en archivos:
- `tools/collector/.token_github`
- `tools/assigner/.token_github`
- `tools/indexer/.token_opensearch`

## 🎯 Características

✅ **Asignación automática** al crear tickets  
✅ **Balance de carga** (asigna al que tiene menos tickets)  
✅ **Sincronización GitHub ↔ OpenSearch** via GitHub Actions  
✅ **Auditoría continua** cada 5 minutos  
✅ **Resiliencia** (errores no bloquean la creación)  
✅ **Límite configurable** (MAX_TICKETS_PER_USER = 2)  

## 📝 Notas

- Dos procesos independientes: collector y auditor
- Usuario `wazuh-community` excluido de asignación
- Errores en asignación no bloquean la creación del ticket
- GitHub Actions mantiene OpenSearch sincronizado con GitHub
