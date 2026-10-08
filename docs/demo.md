# Guía de demostración

1. Instalar dependencias siguiendo README.md y ejecutar `demo.py`.
2. Abrir http://127.0.0.1:8799/ y pulsar Buscar oportunidades.
3. Revisar la puntuación, sus motivos y los datos desconocidos.
4. Mostrar las excluidas para revisar las citas que justifican cada filtro.
5. Cambiar Ordenar por entre relevancia y fecha.
6. Guardar una oferta y marcar otra como Me interesa. Consultar Mis ofertas y sus contadores; pulsar la misma acción para quitarla.
7. Descartar una oferta con motivo y nota. Repetir la búsqueda: las ya valoradas o guardadas se omiten.
8. Consultar historial y ajustes. Las propuestas de pesos requieren suficientes valoraciones; una sola decisión no genera aprendizaje automático.

La banda de demostración identifica los datos ficticios. Las fechas se generan al consultar para que los ejemplos sigan siendo recientes. Se incluye un ejemplo de texto que intenta dar instrucciones a la IA, destinado a mostrar por qué el contenido de un anuncio se trata como datos no confiables.

La IA real está desactivada en la demo. Se describe su implementación en la documentación; demostrar una consulta real requiere credenciales y saldo propios. El almacenamiento de demo está en `worktmp/demo`, separado del modo real y excluido de Git.
