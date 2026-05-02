# OpenSearch Indexer

Indexer sencillo para documentos con relaciones padre/hijo en OpenSearch.

## Características

- ✅ Indexación de documentos padre (mensajes principales, issues)
- ✅ Indexación de documentos hijo (comentarios, respuestas en threads)
- ✅ Relación padre/hijo usando `join` field de OpenSearch
- ✅ Soporte para datos de Slack y GitHub
- ✅ Índice destino: `tickets-raw-v1.0`

## Configuración

### 1. Token de OpenSearch

Crea un archivo `.token_opensearch` en el directorio `tools/indexer/` con tu password de OpenSearch:

```bash
echo "tu_password_aqui" > tools/indexer/.token_opensearch
```

### 2. Variables de entorno (opcional)

Puedes personalizar la configuración editando las variables en `opensearch_indexer.py`:

```python
OPENSEARCH_HOST = "https://search-community-metrics-oevnczvd7jexwstzykmjwj7ak4.aos.us-east-1.on.aws"
INDEX_NAME = "tickets-raw-v1.0"
USERNAME = "community"
```

## Uso

### Como módulo importado

```python
from indexer.opensearch_indexer import (
    OpenSearchIndexer, 
    create_slack_parent_document,
    create_slack_comment_document
)

# Inicializar indexer
indexer = OpenSearchIndexer()

# Crear e indexar un documento padre
parent_doc = create_slack_parent_document(
    message_ts="1234567890.123456",
    channel_id="C1234567890",
    channel_name="general",
    user_id="U1234567890",
    user_name="john.doe",
    content="Este es un mensaje principal",
    permalink="https://workspace.slack.com/archives/C1234567890/p1234567890123456",
    github_issue_number=123,
    github_issue_url="https://github.com/org/repo/issues/123",
    labels=["platform/slack", "slack/channel/general"]
)

indexer.index_parent(parent_doc)

# Crear e indexar un comentario
comment_doc = create_slack_comment_document(
    message_ts="1234567890.123457",
    thread_ts="1234567890.123456",  # Timestamp del padre
    channel_id="C1234567890",
    user_id="U0987654321",
    user_name="jane.smith",
    content="Esta es una respuesta en el thread",
    permalink="https://workspace.slack.com/archives/C1234567890/p1234567890123457",
    github_comment_id=456
)

# El parent_id debe coincidir con el id del documento padre
parent_id = f"slack_{parent_doc['slack_channel_id']}_{parent_doc['slack_message_ts']}"
indexer.index_comment(comment_doc, parent_id)
```

### Indexación en lote

```python
# Preparar múltiples documentos
documents = [
    {
        'id': 'doc1',
        'document_type': 'parent',
        'platform': 'slack',
        'content': 'Contenido 1',
        # ... otros campos
    },
    {
        'id': 'doc2',
        'document_type': 'comment',
        'parent_id': 'doc1',
        'platform': 'slack',
        'content': 'Comentario para doc1',
        # ... otros campos
    }
]

# Indexar en lote
result = indexer.bulk_index(documents)
print(f"Éxito: {result['success']}, Fallos: {result['failed']}")
```

### Test standalone

```bash
cd tools/indexer
python opensearch_indexer.py
```

## Estructura del índice

El índice `tickets-raw-v1.0` tiene la siguiente estructura:

### Campos comunes

- `document_type`: "parent" o "comment"
- `relation`: Join field para relación padre/hijo
- `platform`: "slack", "github", etc.
- `created_at`: Fecha de creación
- `content`: Contenido del mensaje
- `content_raw`: Contenido original sin conversión

### Campos de Slack

- `slack_message_ts`: Timestamp del mensaje
- `slack_thread_ts`: Timestamp del thread (si es reply)
- `slack_channel_id`: ID del canal
- `slack_channel_name`: Nombre del canal
- `slack_user_id`: ID del usuario
- `slack_user_name`: Nombre del usuario
- `slack_permalink`: Enlace permanente al mensaje

### Campos de GitHub

- `github_issue_number`: Número del issue
- `github_issue_url`: URL del issue
- `github_comment_id`: ID del comentario
- `github_repository`: Repositorio
- `github_user`: Usuario de GitHub

### Campos de metadatos

- `labels`: Array de etiquetas
- `state`: Estado del documento
- `assignee`: Asignado

## Relación padre/hijo

OpenSearch usa el campo `relation` para establecer relaciones:

**Documento padre:**
```json
{
  "id": "slack_C123_1234567890.123456",
  "document_type": "parent",
  "relation": {
    "name": "parent"
  },
  "content": "Mensaje principal"
}
```

**Documento hijo:**
```json
{
  "id": "slack_C123_1234567890.123457",
  "document_type": "comment",
  "relation": {
    "name": "comment",
    "parent": "slack_C123_1234567890.123456"
  },
  "content": "Respuesta al mensaje"
}
```

Los documentos hijo se almacenan en el mismo shard que el padre usando `routing`.

## Integración con slack_gw_v2.py

El indexer se integra automáticamente en `slack_gw_v2.py`:

1. Cuando se crea un **parent issue** (mensaje principal):
   - Se crea el issue en GitHub
   - Se indexa como documento padre en OpenSearch

2. Cuando se añade un **thread comment** (respuesta):
   - Se añade el comentario al issue en GitHub
   - Se indexa como documento hijo relacionado con el padre

## Troubleshooting

### Error: "OpenSearch indexer disabled"

- Verifica que existe `.token_opensearch` con el password correcto
- Revisa los permisos del archivo

### Error: "Error checking index existence"

- Verifica la conectividad con el host de OpenSearch
- Comprueba las credenciales (usuario/password)
- Revisa que el host es correcto

### Documentos no aparecen relacionados

- Asegúrate de que el `parent_id` en comentarios coincide con el `id` del padre
- Verifica que el `routing` se está aplicando correctamente
- Usa queries con `has_parent` o `has_child` para buscar documentos relacionados

## Queries de ejemplo

### Buscar todos los padres

```json
GET tickets-raw-v1.0/_search
{
  "query": {
    "term": {
      "document_type": "parent"
    }
  }
}
```

### Buscar comentarios de un padre específico

```json
GET tickets-raw-v1.0/_search
{
  "query": {
    "has_parent": {
      "parent_type": "parent",
      "query": {
        "term": {
          "_id": "slack_C123_1234567890.123456"
        }
      }
    }
  }
}
```

### Buscar padres que tienen comentarios con texto específico

```json
GET tickets-raw-v1.0/_search
{
  "query": {
    "has_child": {
      "type": "comment",
      "query": {
        "match": {
          "content": "error"
        }
      }
    }
  }
}
```
