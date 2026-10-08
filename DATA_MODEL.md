# Modelo de datos

SQLite en `jobflow.db`. Todas las fechas internas se guardan como UTC sin zona en la columna; la API convierte las fechas de publicación a formato ISO de día. No se confunde publicación con recuperación o actualización.

| Tabla | Contenido |
|---|---|
| `sources` | Catálogo, tipo de acceso, estado, última consulta y error |
| `searches` | Términos, radio, antigüedad, parámetros completos, mensajes y total estimado |
| `source_runs` | Fuente y búsqueda, hora, éxito/error, cantidad recibida y duración |
| `api_usage` | Intentos de Adzuna, incluidos los fallidos; endpoint sin claves |
| `jobs` | Oferta lógica, contenido normalizado, coordenadas y calidad, fecha, jornada, primera/última observación, posible republicación |
| `job_sources` | Identidad en la fuente, URL original proporcionada, URL de candidatura si consta y fecha de recuperación |
| `job_aliases` | Identidades agrupadas; permite que los botones de búsquedas antiguas sigan usando la oferta conservada |
| `search_results` | Relación búsqueda/oferta, estado, motivo de exclusión, citas, puntuación y snapshot JSON |
| `job_feedback` | Valoración actual, favorito independiente, motivo y nota opcionales |
| `analysis_cache` | JSON validado por hash de contenido, versión de prompt y nombre del modelo |
| `search_cache` | Respuesta de búsqueda por hash de parámetros públicos, vigente 15 minutos |
| `llm_usage` | Intentos de OpenAI para el límite local de 24 horas |

## Identidad y conservación

`job_sources(source_id, source_job_id)` y `search_results(search_id, job_id)` son únicos. La misma identidad de fuente actualiza su oferta; una URL canónica igual se une a la oferta existente. Se eliminan de la canonicalización solo parámetros conocidos `utm_*` y fragmentos, conservando los parámetros que pueden identificar el anuncio.

Una coincidencia de título, empresa y lugar con texto muy similar y el mismo día puede agruparse en la búsqueda; sus enlaces pasan a la oferta conservada. Con fecha distinta se señala como posible republicación, sin borrar registros. La normalización de empresa es deliberadamente mínima; no se equiparan nombres de entidades diferentes por suposiciones.

Una exclusión pertenece a su búsqueda: cambiar el radio o un filtro no altera silenciosamente las búsquedas anteriores. El snapshot permite recuperar la explicación que se mostró. El registro de oferta lógica se mantiene y las valoraciones actuales se recuperan por ID, independientemente de la búsqueda.

Al agrupar dos ofertas se conserva un favorito presente en cualquiera de ellas y la valoración vigente más reciente. El ID agrupado queda como alias, por lo que una valoración desde un resultado histórico afecta a la misma oferta lógica y no se pierde por la agrupación.

El favorito es independiente del interés/rechazo. Quitar una valoración no elimina el favorito. Los recuentos de motivos corresponden a las valoraciones actuales de rechazo; no hay motor de aprendizaje ni registro de candidaturas.

## Migraciones y privacidad

`migrations.py` añade columnas cuando faltan y convierte las valoraciones antiguas de `liked` a interesado/rechazado. Las migraciones son idempotentes y no eliminan tablas o filas. Antes de la primera actualización se crea `jobflow.db.bak`. También se conservan los resultados de versiones anteriores cuando existe su relación de búsqueda.

`config/qualifications.yaml` es opcional, local y excluido de Git. La plantilla pública es `qualifications.example.yaml`. `.env`, SQLite y carpetas de prueba también se excluyen. Ninguna tabla almacena las claves Adzuna/OpenAI. El perfil de titulaciones no se envía al servicio de IA.

El historial antiguo de la Fase 2 puede no tener resultados asociados, porque esa versión todavía no registraba esa relación. No se inventan asociaciones entre ofertas y búsquedas pasadas. Una nueva búsqueda vuelve a relacionar las ofertas recibidas y conserva su identidad/valoración.

## Decisiones de preferencias

`learning_decisions` guarda identificador único de propuesta, criterio, dirección, peso anterior y propuesto, estado (accepted/dismissed/undone), evidencia con IDs de ofertas y fecha de creación. Se crea como tabla adicional al arrancar; no modifica ni borra las valoraciones existentes. Las señales aceptadas o deshechas se consideran consumidas para evitar aplicar varias veces el mismo aprendizaje.

`job_feedback.interest_note` conserva la explicación de un interés o guardado, separada de `note` (rechazo). `interest_conditional` indica si solo interesa una variante o condición; por defecto es falso para valoraciones existentes. Las migraciones añaden ambas columnas sin modificar las notas previas. Los duplicados conservan la explicación y el carácter condicional.
