# Arquitectura y decisiones

FastAPI sirve una interfaz HTML/CSS/JavaScript y endpoints con contratos Pydantic. SQLAlchemy conserva ofertas, fuentes, resultados de búsqueda y valoraciones en SQLite. Configuración y patrones legibles viven en YAML.

## Flujo de una búsqueda

1. Validar palabras, radio, antigüedad y jornadas.
2. Obtener candidatos de Adzuna, o de fixtures en la demo.
3. Normalizar fechas, campos e identidad; conservar datos desconocidos.
4. Agrupar coincidencias claras y conservar feedback asociado.
5. Omitir ofertas ya valoradas o guardadas de las búsquedas nuevas.
6. Aplicar exclusiones solo con información explícita.
7. Extraer criterios localmente y calcular relevancia y puntuación explicable.
8. Guardar una instantánea; superponer la valoración actual al consultar historial o biblioteca.

## IA opcional

El usuario selecciona ofertas y consulta una vista previa de llamadas nuevas, análisis guardados y límite restante. La API Responses devuelve un contrato estricto de datos y evidencia. Las citas se comprueban contra el título y el extracto. Se cachea por contenido, prompt/esquema y modelo. Si la respuesta es inválida o falla el proveedor, se conserva la extracción local.

El anuncio se trata como contenido no confiable. La IA no modifica filtros, ejecuta código ni descarga páginas originales. Validar una cita no demuestra por sí solo que la interpretación sea correcta.

## Preferencias

Las valoraciones y motivos concretos generan asociaciones locales. Se requieren señales suficientes para proponer un pequeño cambio de peso; aceptar, descartar y deshacer quedan registrados. Guardar por sí solo no significa interés. Una explicación condicional no se interpreta como aprobación de todas las condiciones del anuncio.

## Persistencia y seguridad

SQLite y migraciones aditivas conservan datos. El navegador recuerda filtros, no claves. Los enlaces se validan; la interfaz utiliza textContent, CSP, hosts permitidos y comprobación de origen para escrituras. La preparación online añade contraseña derivada con PBKDF2, cookies firmadas, límite de intentos y datos en una carpeta persistente. Necesita comprobación de despliegue antes de uso online.

## Decisiones de alcance

Se usa un proceso y una base local para mantener sencilla una aplicación de una persona. Las APIs externas tienen timeout, caché y cuotas locales. Los demás portales se identifican como enlaces. La demo sustituye solo la obtención de candidatos; conserva el flujo de normalización, filtrado, valoración y persistencia de la app.
