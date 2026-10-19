# Implementación de la solución — Nox

**Proyecto:** asistente conversacional de Logic Escape Room  
**Tipo de documento:** investigación técnica, matriz de trazabilidad y borrador académico para el PFM  
**Fecha de revisión del repositorio:** 18 de octubre de 2026

## Alcance y método de revisión

Este documento describe lo verificable en el código, las pruebas y los artefactos disponibles en el repositorio. Se revisaron las fases 1 a 7, la estructura del proyecto, las dependencias, los módulos de backend y frontend, los documentos del corpus RAG, las pruebas automatizadas, el dataset y los resultados conservados de evaluación, además del historial Git.

Se ejecutaron localmente las pruebas existentes del backend (`139 passed`). La compilación más reciente registrada del frontend, mediante `npm.cmd run build`, también terminó correctamente. No se repitieron llamadas a OpenAI ni a la API desplegada durante esta investigación. El informe distingue por ello las pruebas simuladas, las consultas externas registradas previamente, las conversaciones manuales compartidas durante el desarrollo y las validaciones aún pendientes.

El `HEAD` de Git revisado corresponde a `32832660c8ab415d0c62f2e9210d772ae2ebb732` (`UI cretation and initial testing`). El árbol de trabajo contiene modificaciones y archivos nuevos no confirmados. Por tanto, ese commit identifica la base Git, pero no representa por sí solo todo el código y la documentación que se inspeccionaron.

# Entregable A. Informe de investigación técnica

## A.1. Solución comprobada

Nox es un prototipo de atención conversacional en español compuesto por una interfaz web React, un backend FastAPI, un modelo de lenguaje configurable mediante OpenAI SDK, una base documental recuperada con embeddings y Chroma, y un cliente tipado para las operaciones de lectura de la API de Logic Escape Room. El backend limita las rutas disponibles, valida la selección estructurada del modelo, ejecuta las herramientas autorizadas y prepara evidencia para generar la respuesta.

La API es la fuente de salas activas, atributos estructurados, tarifas, cotizaciones concretas, horarios generales y disponibilidad por fecha. El RAG es la fuente complementaria de políticas, excepciones, recomendaciones y preguntas frecuentes documentadas. La configuración de entorno conserva datos operativos mutables, como enlaces y datos de pago verificados. El modelo interpreta el mensaje y redacta; no es la fuente autorizada de esos hechos.

La interfaz conserva el transcript en memoria de la sesión y envía hasta ocho mensajes anteriores junto con el mensaje actual. La conversación no se persiste en el navegador mediante almacenamiento local. El límite de contexto puede hacer que referencias más antiguas dejen de estar disponibles.

## A.2. Tecnologías e integraciones observadas

| Componente | Tecnología comprobada | Responsabilidad |
|---|---|---|
| Backend | Python, FastAPI, Pydantic | Endpoint de chat, validación del contrato y composición de componentes. |
| Cliente Logic | httpx asíncrono y modelos Pydantic | Llamadas con timeout, validación de respuestas y traducción de errores. |
| LLM y embeddings | OpenAI SDK | Selección estructurada de una ruta, redacción basada en evidencia y creación de embeddings. El modelo y los parámetros se configuran por entorno. |
| RAG | Chroma persistente local, Markdown, YAML, JSON Schema | Ingesta validada del corpus indexado y recuperación semántica con metadatos trazables. |
| Caché | cachetools, TTL en memoria de proceso | Caché de salas, tarifas y horarios generales; no almacena disponibilidad ni cotizaciones. TTL predeterminado: 43.200 segundos. |
| Interfaz | React, TypeScript y Vite | Chat web, transcript temporal, carga, errores, reintento y nueva conversación. |
| Pruebas | pytest | Pruebas unitarias y de integración aislada con respuestas simuladas; no se encontró una suite automatizada de frontend. |
| Evaluación | Runner Python propio y JSON/JSONL | Ejecución repetible del dataset, trazas, métricas automáticas y campos para revisión manual. |

No se encontraron LangChain, Redis, infraestructura distribuida, autenticación de usuarios, creación de reservas ni despliegue del asistente en un proveedor cloud dentro del alcance verificado.

## A.3. Flujo técnico

1. El navegador envía `POST /api/chat` con el nuevo mensaje y hasta ocho mensajes previos.
2. El backend entrega el contexto al selector del modelo, que debe devolver exactamente una ruta incluida en un esquema cerrado. Las rutas admitidas son `get_rooms`, `get_rates`, `get_opening_hours`, `get_quote`, `get_availability`, `search_business_knowledge`, `check_room_policy` y `clarify`.
3. El orquestador normaliza fechas y referencias conversacionales, comprueba si faltan datos y puede ajustar una selección incompleta en los casos cubiertos por reglas explícitas. Por ejemplo, una solicitud fechada de reserva se dirige a disponibilidad; al escoger una franja ofrecida se recuperan sala y fecha del contexto reciente.
4. Las herramientas del backend consultan Logic, Chroma o la configuración operativa. Los resultados pasan por modelos y adaptadores permitidos; los objetos crudos de salas no se entregan directamente al modelo.
5. La orquestación combina evidencia API y RAG cuando una política contextual depende de datos actuales. Ante evidencia insuficiente, errores o una excepción no confirmada, solicita aclaración o produce una salida de revisión humana.
6. El modelo genera una respuesta en español a partir de la evidencia recibida. La API devuelve `answer` y puede devolver también `messages` para permitir respuestas separadas por temas.

El flujo es acotado: no implementa un ciclo autónomo de herramientas. La disponibilidad es una consulta puntual y no bloquea una franja. No se ejecuta `POST /api/bookings`.

## A.4. API, RAG y operación de reservas

El cliente Logic usa las cinco operaciones documentadas: `GET /api/rooms`, `GET /api/rates`, `GET /api/bookings/quote`, `GET /api/bookings/opening-hours` y `GET /api/bookings/availability`. La cotización concreta se delega al endpoint de quote en lugar de calcular el total desde memoria. Disponibilidad requiere una consulta nueva y no se cachea. El cliente diferencia errores funcionales `400`, conflictos `409`, errores `5xx`, timeout y respuesta inválida.

El adaptador de salas conserva un conjunto explícito de atributos para el asistente y descarta campos ajenos al DTO. La disponibilidad transforma las franjas a la zona horaria `America/Bogota` y evita enviar el identificador interno de sala en la respuesta normal al modelo.

El corpus RAG se limita a los archivos enlazados desde `knowledge/INDEX.md`. Los documentos contienen metadatos de categoría, versión, fuente, fecha y estado de validación. La ingesta valida esquema y rutas, conserva el documento de política como unidad semántica y sincroniza embeddings en una colección persistente local. La recuperación admite filtros por sala y categoría, límite de distancia y metadatos de procedencia. Los datos dinámicos de precios, salas activas, disponibilidad y llaves de pago están excluidos del corpus.

Hay lógica para completar una solicitud conversacional cuando se recopilan sala, fecha, franja, número de participantes, nombre y celular. Si la configuración operativa está marcada como verificada, la respuesta final puede resumir la solicitud e incluir instrucciones de abono. Esto constituye una instrucción conversacional; el sistema no procesa el pago, no inspecciona comprobantes, no crea la reserva ni recibe una confirmación de la API.

El código y las políticas contemplan la revisión humana, y la respuesta puede informar que el equipo deberá revisar un caso. Sin embargo, no existe integración con un inbox, creación de ticket, aplicación de tag ni cambio de estado de lectura. Por ello no se puede afirmar que una persona haya sido notificada por una acción técnica del sistema.

## A.5. Pruebas y resultados observados

### Pruebas automatizadas

En la revisión se ejecutó `python -m pytest tests -q` desde `backend/`: **139 pruebas pasaron**. Los módulos cubren el cliente HTTP, el adaptador, la caché, la ingesta y recuperación RAG, la orquestación, reglas de conversación, el endpoint de salud y el runner de evaluación. Las pruebas de Logic emplean respuestas HTTP simuladas; no representan una comprobación en vivo de cada llamada.

La compilación de frontend se comprobó con `npm.cmd run build`: TypeScript y Vite terminaron sin errores. No se encontraron pruebas automatizadas de comportamiento React.

### Evaluación repetible preservada

El dataset `evaluation/cases.json` tiene versión `1.0.0` y **40 casos**, balanceados en cuatro categorías de diez: preguntas generales/estructuradas; salas, precios y condiciones; disponibilidad/cotización; y ambigüedad, falta de soporte o excepciones.

El resumen más reciente identifica la corrida `dd5fca9e91f24ae68ff23de426eb2caf`, fechada el 18 de octubre de 2026, con `gpt-6-luna`. Sus resultados son: exactitud de ruta `1,00`, exactitud de fuente `1,00`, cero casos con errores, latencia media `5,332 s`, mediana `5,224 s` y percentil 95 `7,679 s`. Son métricas del runner sobre el dataset y esa configuración; no miden resolución satisfactoria para clientes.

La revisión manual está vacía: `reviewed_cases = 0`; fidelidad, relevancia y tasa de afirmaciones no sustentadas son nulas/no medidas. Los estados HTTP exitosos tampoco quedan registrados por el cliente, de modo que los códigos HTTP de éxito aparecen vacíos en las trazas.

El repositorio conserva once ejecuciones de 40 filas (440 registros JSONL). La última se puede seleccionar mediante `run_id`. El manifiesto de entrega encontró que el hash del prompt reportado por la corrida difiere del archivo actual y que el runner no guardó el diff ni el estado del árbol de trabajo. La corrida es evidencia histórica y no acredita por sí sola el estado actual.

### Validación manual y piloto

Durante el desarrollo se compartieron capturas de conversaciones en el chat de trabajo para examinar preguntas generales, variaciones de formulación, precios, menores, selección de salas y horarios, datos de contacto, cierre de conversación y resumen de solicitud. Estas observaciones impulsaron ajustes y pruebas automatizadas de regresión. No se encontró un protocolo, conjunto de transcripciones exportado ni rúbrica que permita cuantificar esa validación manual.

No hay evidencia de un piloto con clientes reales, participantes reclutados, cuestionarios respondidos ni mediciones de satisfacción. En consecuencia, no se atribuye al proyecto una mejora empresarial ni una reducción medida de tiempos de atención o reservas completadas.

## A.6. Correcciones de desarrollo respaldadas

Las pruebas y el código muestran trabajo iterativo en estas áreas:

- **Continuidad al escoger una hora:** recuperación de sala y fecha ofrecidas en turnos recientes, incluidas frases alternativas y fechas escritas con día numérico.
- **Intención de reserva por temática:** asociación de descriptores como terror con salas activas cuando el catálogo y su descripción recuperada lo sustentan; no se generaliza una categoría a una sala que no coincide.
- **Seguimientos de precio:** conservación del número de participantes y contexto de día/fecha, uso de tarifas de referencia sin fecha exacta y endpoint de cotización cuando existe información concreta.
- **Preguntas generales sobre la actividad:** rutas para explicar qué es un escape room, responder seguimientos como una pregunta por video y ofrecer información de salas.
- **Recopilación de datos:** conservación de nombre o teléfono aportado en turnos distintos, resumen cuando se reúnen los campos previstos e instrucciones configurables de abono.
- **Flujo de conversación:** saludos iniciales, agradecimientos/despedidas y preguntas de continuidad; evitar que una pregunta de precio posterior se confunda con datos de contacto o que se repita mecánicamente el resumen.
- **Reglas y excepciones:** combinación de atributos actuales de API con políticas RAG, filtrado por sala y revisión cuando la excepción no queda sustentada.

Estos casos demuestran cobertura de ejemplos concretos y pruebas de regresión; no prueban comprensión perfecta de todas las expresiones naturales posibles.

## A.7. Limitaciones y datos faltantes

La API de Logic no ofrece autenticación servidor-a-servidor. El endpoint de chat tampoco incorpora autenticación de usuarios ni limitación de solicitudes. No hay workflow de consentimiento, aviso de privacidad, retención y eliminación, ni despliegue documentado para el asistente. El historial enviado al modelo puede incluir nombres o teléfonos compartidos durante una solicitud.

El protocolo API de salas refleja el esquema existente y no un DTO público versionado. La recuperación RAG depende de la calidad y actualización del corpus, y el comportamiento basado en texto no garantiza coincidencias para toda paráfrasis. El contexto conversacional está limitado a ocho turnos.

La plataforma no escribe reservas ni confirma el pago. La lógica puede compartir datos de abono configurados, pero el equipo humano debe verificarlo fuera del asistente. Tampoco existe integración para notificar o transferir automáticamente una conversación a una persona.

No están medidos el uso real, el volumen concurrente, costos por conversación, tasa de resolución, calidad factual manual, percepción de clientes, tiempo ahorrado, porcentaje de reservas completadas ni impacto comercial. Tampoco se encontró auditoría de vulnerabilidades de dependencias, prueba de carga o prueba de penetración.

## A.8. Matriz de trazabilidad

| Funcionalidad o decisión | Fase | Evidencia en el repositorio | Prueba asociada | Estado actual |
|---|---|---|---|---|
| Servicio backend, configuración por entorno y salud | 1 | `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/api/health.py`, `docs/01_PHASE_BOOTSTRAP.md` | `backend/tests/test_health.py`; suite completa | Implementado localmente; sin despliegue del asistente verificado. |
| Lecturas estructuradas de Logic y adaptador seguro de salas | 2 | `backend/app/logic_api/client.py`, `models.py`, `adapter.py`, `cache.py`; `specs/logic-readonly-interfaces.md` | `backend/tests/test_logic_api_client.py` | Implementado; pruebas con cliente/respuestas simuladas. El API desplegado se consultó anteriormente según registro documental. |
| Corpus RAG, validación, embeddings y Chroma persistente | 3 | `knowledge/`, `config/knowledge-schema.json`, `backend/app/rag/`, `docs/03_PHASE_RAG.md` | `backend/tests/test_knowledge_assets.py`, `test_rag.py` | Implementado localmente; ingesta real depende de credenciales del proveedor y ejecución. |
| Selección de ruta acotada y combinación API/RAG | 4 | `backend/app/assistant/model.py`, `orchestrator.py`, `tools.py`, `response_builder.py`, `agent/nox-system.md` | `backend/tests/test_orchestration.py` | Implementado; decisiones de modelo/reglas cubiertas con mocks. |
| Interfaz web y contexto conversacional de ocho mensajes | 5 | `frontend/src/App.tsx`, `frontend/vite.config.ts`, `docs/05_PHASE_FRONTEND.md` | Build TypeScript/Vite; no hay suite de pruebas UI localizada | Build aprobado; uso manual exploratorio, sin piloto formal. |
| Dataset, trazas y métricas repetibles | 6 | `backend/app/evaluation/`, `evaluation/cases.json`, `evaluation/results/`, `docs/06_PHASE_EVALUATION.md` | `backend/tests/test_evaluation.py`; corrida histórica de 40 casos | Implementado y ejecutado; revisión humana pendiente y versión actual no certificada. |
| Revisión de seguridad, limitaciones y evidencia de entrega | 7 | `docs/07_PHASE_HARDENING.md`, `docs/08_ENVIRONMENT_AND_COMMANDS.md`, `evaluation/results/release_manifest.json` | Revisión documental, búsqueda de rutas y patrones de secretos; suite backend | Revisión documental completada; persisten brechas antes de producción. |
| Precio orientativo y cotización total | 2 y 4 | `backend/app/logic_api/client.py`, `backend/app/assistant/orchestrator.py` | Casos de tarifas, seguimientos y quote en `test_logic_api_client.py` y `test_orchestration.py` | API de referencia y quote implementados; no se calcula manualmente el total. |
| Disponibilidad en vivo y continuidad al elegir horario | 2 y 4 | `client.py`, `orchestrator.py`, `tools.py` | Casos `test_time_choice_*`, `test_reservation_intent_*` en `test_orchestration.py` | Implementado; disponibilidad es instantánea y no bloquea sala. |
| Reglas de edad, aforo y excepción contextual | 3 y 4 | `knowledge/policies/minors-and-room-limits.md`, `tools.py`, `orchestrator.py` | Casos de menores, capacidad, API+RAG y no generalización | Implementado según documentos y pruebas; vigencia comercial requiere aprobación del responsable. |
| Resumen de solicitud e instrucciones de abono | 4 (ampliación funcional durante iteración) | `_completed_reservation_message` en `orchestrator.py`; configuración en `core/config.py` | `test_combined_name_and_phone_complete_reservation_summary_and_payment_instructions` | Mensaje condicionado a configuración verificada; sin pago ni escritura de reserva. |
| Transferencia efectiva a una persona/inbox | Pendiente fuera de las fases funcionales | `specs/logic-readonly-interfaces.md`, `quality/unresolved-decisions.md` | No existe integración ni prueba de inbox | No implementado; el asistente solo puede comunicar que requiere revisión humana. |

Las fases indican la etapa de diseño y entrega asociada; los casos conversacionales evolucionaron de forma iterativa y no todos se incorporaron en el mismo commit. El estado Git y la falta de una corrida congelada se describen en el apartado de evaluación.

# Entregable B. Apartado académico propuesto

## 3.1. Introducción a la implementación

La etapa de implementación materializó un prototipo conversacional para atender consultas frecuentes de clientes de Logic Escape Room. El objetivo técnico fue integrar una interfaz sencilla con fuentes de información diferenciadas: la API del negocio para datos estructurados y cambiantes, una base documental para políticas y excepciones, y un modelo de lenguaje para interpretar consultas y redactar respuestas en español.

La solución se diseñó con límites explícitos para evitar que el modelo generara por sí solo tarifas, disponibilidad o condiciones operativas. El backend conserva la responsabilidad de validar rutas, consultar las fuentes autorizadas y preparar evidencia. En consecuencia, el alcance desarrollado corresponde a una herramienta de información y apoyo a la conversación; no equivale a un sistema de reservas transaccional ni a una plataforma de atención humana.

## 3.2. Entorno de desarrollo y tecnologías utilizadas

El backend se implementó en Python con FastAPI y Pydantic. FastAPI expone el endpoint de conversación y el endpoint de salud; Pydantic define y valida mensajes, rutas, respuestas y objetos recibidos de Logic. El cliente de la API utiliza httpx asíncrono con timeouts y tipos de error diferenciados. `cachetools` sostiene una caché TTL en memoria de proceso para los datos de referencia de baja variación.

La integración con el modelo se realizó mediante OpenAI SDK, con credenciales, nombre del modelo, esfuerzo de razonamiento, timeout y límite de salida configurables por variables de entorno. El mismo proveedor se usa para generar embeddings, con modelo también configurable. La recuperación semántica utiliza Chroma persistente local; el conocimiento se mantiene en Markdown con metadatos YAML validados mediante JSON Schema. Pytest se empleó para las pruebas del backend.

La interfaz se construyó con React, TypeScript y Vite. Consume únicamente el endpoint `/api/chat` del backend. En la ejecución de desarrollo, Vite puede reenviar las solicitudes `/api` al backend local. La configuración de la URL de Logic y las credenciales del modelo permanece en el servidor.

## 3.3. Proceso de implementación

La solución se organizó por componentes funcionales, correspondientes a las siete fases del proyecto. Primero se establecieron la estructura del servicio y la configuración por entorno. Después se desarrolló el cliente tipado de Logic, que expone las operaciones de salas, tarifas, cotización, horario y disponibilidad, incorpora control de errores y restringe qué datos de sala se presentan al modelo.

En paralelo se estructuró el corpus RAG y su índice. La ingesta valida archivos y metadatos, obtiene embeddings y actualiza una colección Chroma local. El recuperador devuelve documentos con identificador, categoría, procedencia y distancia, lo que permite comprobar qué evidencia se utilizó y descartar coincidencias débiles.

La orquestación implementó un conjunto cerrado de rutas. El modelo selecciona una operación mediante una respuesta estructurada; el backend valida sus argumentos y ejecuta la herramienta autorizada. Reglas deterministas complementan la selección en flujos donde las pruebas identificaron fallos de continuidad, como una fecha relativa, una temática de sala o una hora elegida después de una oferta de disponibilidad. La respuesta final se genera con los datos recuperados o se solicita aclaración cuando faltan campos.

La interfaz web muestra mensajes, estado de carga, errores con posibilidad de reintento y una acción para iniciar otra conversación. La Fase 6 añadió 40 escenarios y un runner que genera JSONL de trazas y un resumen de métricas. La Fase 7 documentó la revisión de seguridad, las limitaciones de producción y los artefactos preservados.

## 3.4. Integración de los componentes de la solución

La persona usuaria interactúa con el chat desde el navegador. La aplicación envía el texto y el contexto reciente al backend. El selector del modelo elige una sola ruta en un esquema cerrado; no ejecuta directamente consultas ni recibe objetos crudos de la API. El backend consulta Logic para información estructurada o Chroma para información documental y, cuando corresponde, combina ambos tipos de evidencia antes de redactar.

La consulta de una tarifa general se resuelve con los rangos de la API. Una cotización concreta requiere fecha y número de participantes y se delega al endpoint de quote. Una pregunta sobre disponibilidad requiere fecha y genera una lectura actual. Las políticas de edad, excepciones, eventos y atención al cliente se buscan en el corpus; si dependen de una capacidad o sala, se combinan con la respuesta vigente del API.

Si el dato requerido falta, el backend pregunta por él. Si la API falla, la respuesta no debe convertir el fallo en una afirmación de falta de disponibilidad. Si la política no resulta aplicable con claridad, el flujo puede indicar que el equipo debe revisar el caso. Esta indicación es textual: el repositorio no implementa el envío automático de la conversación a un asesor.

El flujo puede recopilar los datos necesarios para describir una solicitud de reserva y, si la configuración operativa está verificada, mostrar instrucciones de abono. No se crea una reserva en Logic, no se procesa un pago y no se recibe confirmación de un humano. Por tanto, el resumen y las instrucciones no deben describirse como una reserva confirmada.

## 3.5. Pruebas y validación funcional

La tabla diferencia pruebas automatizadas, consultas externas registradas y observaciones manuales. El estado “aprobado” en las pruebas automatizadas indica que la prueba correspondiente pasó en el entorno local; no constituye validación de efectividad con clientes.

| Identificador | Escenario evaluado | Resultado esperado | Resultado obtenido | Estado | Evidencia |
|---|---|---|---|---|---|
| AUT-API-01 | Lecturas de salas, tarifas, quote, horarios y disponibilidad con modelos tipados | Usar rutas permitidas y validar las respuestas | Las pruebas de cliente cubren las cinco rutas documentadas y los modelos | Aprobado en pruebas simuladas | `backend/tests/test_logic_api_client.py` |
| AUT-API-02 | Parámetros inválidos, día cerrado, horario ausente, conflicto, error del servidor y timeout | Rechazar parámetros inválidos y distinguir errores sin inventar disponibilidad | Los casos automatizados verifican validaciones y errores tipados | Aprobado en pruebas simuladas | `test_logic_api_client.py`; `test_orchestration.py` |
| AUT-API-03 | Caché de datos de referencia frente a datos dinámicos | Cachear salas, tarifas y horario; no cachear quote ni disponibilidad | Prueba específica de caché ejecutada | Aprobado en pruebas simuladas | `test_logic_api_client.py::test_only_reference_data_is_cached` |
| AUT-RAG-01 | Carga del índice, metadatos, unidad semántica y sincronización | Cargar solo documentos enlazados y conservar procedencia | Pruebas validan índice, metadatos y persistencia con colección de prueba | Aprobado localmente | `backend/tests/test_knowledge_assets.py`, `test_rag.py` |
| AUT-RAG-02 | Política aplicable, filtro por sala y recuperación débil | Recuperar evidencia pertinente, excluir política de otra sala y descartar distancia alta | Pruebas específicas presentes y pasadas | Aprobado localmente | `test_rag.py` |
| AUT-ORQ-01 | Salas, preguntas generales, ubicación, precios y preguntas con varias intenciones | Seleccionar fuentes pertinentes y contestar lo solicitado | Casos cubren catálogo, opciones para solicitudes vagas, mensajes separados y seguimiento de precio | Aprobado en fixtures | `backend/tests/test_orchestration.py` |
| AUT-ORQ-02 | Solicitud fechada y selección de horario ofrecido en lenguaje variado | Consultar disponibilidad y conservar sala/fecha del contexto | Casos cubren fechas, días, temas, hora elegida y oferta previa con fecha numérica | Aprobado en fixtures | `test_orchestration.py`, pruebas `test_time_choice_*` y `test_reservation_intent_*` |
| AUT-ORQ-03 | Menores, capacidades y excepciones | Combinar datos API y reglas RAG, sin generalizar excepciones | Casos cubren acompañamiento, aforo y exclusión de una excepción para otra sala | Aprobado en fixtures | `test_orchestration.py`; `test_rag.py` |
| AUT-ORQ-04 | Nombre y teléfono en turnos separados; resumen final y pregunta posterior de precio | Mantener campos disponibles y no repetir el resumen ante una intención nueva | Existen pruebas de continuidad, resumen y no confusión entre datos de contacto y precio | Aprobado en fixtures | `test_orchestration.py::test_combined_name_and_phone_complete_reservation_summary_and_payment_instructions`; `test_price_question_after_reservation_summary_is_not_mistaken_for_contact_details` |
| AUT-API-04 | Límite de salida del chat | Devolver respuesta de usuario sin evidencia o rutas internas | Prueba del endpoint de chat incluida | Aprobado localmente | `test_orchestration.py::test_chat_endpoint_returns_answer_without_route_or_raw_evidence`; `test_health.py` |
| EVAL-40 | Dataset completo de cuatro categorías | Registrar ruta/fuente esperadas y observadas, latencia, error y campos para revisión | 40 casos; exactitud de ruta 1,00; fuente 1,00; cero casos con error; media 5,332 s | Ejecutado; calidad manual pendiente | `evaluation/cases.json`, `evaluation/results/summary.json`, `raw_runs.jsonl`, `release_manifest.json` |
| INT-API-01 | Consultas directas previas al API desplegado | Confirmar contrato observado de las cinco lecturas | El documento técnico registra respuestas satisfactorias a GET sin credenciales el 17-10-2026; no se repitieron durante esta revisión | Evidencia documental histórica | `specs/logic-readonly-interfaces.md`; `quality/unresolved-decisions.md` |
| MAN-CHAT-01 | Conversaciones con paráfrasis, reserva, precio, sala, edades y cierre | Identificar intención y conservar contexto suficiente | Se reportaron fallos y se añadieron correcciones y regresiones; no existe protocolo o puntuación manual consolidada | Exploratorio, no cuantificado | Capturas compartidas en el historial de trabajo; casos relacionados en `test_orchestration.py` |
| PILOTO-01 | Atención a clientes reales | Medir comprensión, confianza, utilidad, rapidez y resolución | No se encontró reclutamiento, protocolo, respuestas ni datos de participantes | No realizado/no verificable | No hay artefacto de piloto en el repositorio |

El runner evaluó la selección de ruta y fuente frente a las etiquetas del dataset. La ausencia de error técnico no demuestra que la respuesta fuera completa, correcta para el cliente o fiel a las fuentes. Estas propiedades requieren completar la rúbrica manual descrita en la guía de evaluación.

## 3.6. Resultados de la implementación

Quedó operativo un prototipo que responde preguntas informativas, consulta datos estructurados de Logic, recupera reglas documentadas, pregunta por datos faltantes y conserva contexto reciente. El backend y la interfaz se pueden ejecutar localmente; el backend cuenta con 139 pruebas automatizadas aprobadas en la revisión y el frontend se compiló correctamente.

La corrida preservada de 40 casos presentó una exactitud de ruta y fuente del 100 % bajo las definiciones del runner, cero errores y una latencia mediana de 5,224 segundos. El p95 fue 7,679 segundos. Estas cifras se circunscriben a una corrida, a un modelo configurado y al entorno local medido; no deben extrapolarse a latencia de producción ni a satisfacción del cliente.

No existen mediciones verificables de reducción de trabajo humano, tiempo de respuesta frente al proceso previo, consultas resueltas sin asistencia, reservas completadas, ingresos o satisfacción. Tampoco puede calcularse una tasa de alucinación: ninguna de las 40 respuestas tiene puntuación manual.

## 3.7. Ajustes y mejoras realizadas

| Problema observado durante el desarrollo | Ajuste implementado y verificable | Resultado comprobado |
|---|---|---|
| Al escoger una hora ofrecida, el asistente podía preguntar otra vez la sala pese a que ya estaba en el mensaje de horarios. | Recuperación de sala y fecha desde la oferta reciente; prueba para oferta con fecha numérica y selección de hora. | La prueba verifica que la continuación produce ruta de disponibilidad con sala y fecha esperadas. |
| Las frases de reserva podían variar (“sala de terror”, nombre de sala, día u hora) y no siempre llegaban al flujo de disponibilidad. | Reglas de interpretación de temática, fechas relativas y selección del catálogo activo, complementadas por selección del modelo. | Pruebas cubren varias formulaciones y el caso de tema de terror únicamente para salas cuya descripción lo respalda. |
| Una pregunta general sobre más información podía recibir una dirección o una respuesta de desconocimiento. | Ruta de aclaración que ofrece temas disponibles y respuestas para la explicación general de escape room y su seguimiento por video. | Pruebas cubren preguntas de experiencia y video con enlace configurado. |
| Los seguimientos breves sobre precio podían perder cantidad de personas o derivar a una pregunta genérica. | Recuperación de contexto para día/tipo de tarifa, asistentes y cotización concreta. | Pruebas cubren seguimiento con tarifa de referencia y endpoint quote. |
| Los datos de contacto podían interpretarse como una consulta nueva y no completar el flujo iniciado. | Extracción de nombre y celular desde turnos separados y generación del resumen cuando se reúnen los campos requeridos. | Pruebas cubren nombre, teléfono, resumen y consulta de precio posterior. |
| Respuestas de cortesía podían forzar una pregunta adicional; saludos podían recibir un menú genérico. | Reglas para saludo inicial, cierre y preguntas de continuidad pertinentes. | Casos automatizados de saludos, agradecimientos, despedidas y preguntas de seguimiento. |
| Excepciones RAG podían utilizarse fuera de sus condiciones. | Filtro por sala/categoría y controles que requieren evidencia API + política en casos sensibles. | Pruebas de aplicación exacta y no generalización. |

Los resultados anteriores corresponden a escenarios de prueba definidos. La variabilidad lingüística sigue requiriendo evaluación con paráfrasis nuevas y revisión humana de respuestas.

## 3.8. Limitaciones identificadas

El MVP excluye la creación, modificación y consulta de reservas transaccionales. No se conecta a WhatsApp ni a un sistema de bandeja, no registra solicitudes con el personal, no procesa pagos y no verifica comprobantes. La respuesta de disponibilidad informa una instantánea, no una reserva confirmada.

La API actual carece de autenticación servidor-a-servidor y su esquema de salas no está versionado. El asistente no incorpora autenticación de usuario ni limitación de tráfico. El uso de CORS no resolvería estas carencias. El backend transmite al proveedor configurado el mensaje y parte del historial; conversaciones de reserva pueden contener datos personales. Antes de uso real deben definirse aviso, base de tratamiento, acceso, retención y eliminación.

La conversación mantiene como máximo ocho mensajes anteriores. La base vectorial es local a la instalación, y no se documentó una estrategia de respaldo o despliegue. La información del RAG puede quedar desactualizada si no se valida e ingesta el corpus después de cambios operativos.

La corrida de evaluación no almacenó el estado del árbol de trabajo. Además, el hash de prompt difiere del actual. No es posible certificar que esa corrida corresponde íntegramente a la versión revisada. Tampoco hay revisión manual, prueba de carga, auditoría de seguridad externa ni piloto con clientes.

## 3.9. Propuesta de mejora continua

| Horizonte | Propuesta | Indicadores o criterio de avance |
|---|---|---|
| Corto plazo | Congelar código, prompt, dataset y corpus en una revisión limpia; volver a ejecutar los 40 casos; completar revisión manual por caso; añadir casos de las conversaciones problemáticas sin datos personales. | Hashes reproducibles; ruta/fuente; fidelidad, relevancia, abstención correcta y afirmación no sustentada puntuadas. |
| Corto plazo | Revisar con el responsable de Logic las reglas y valores operativos actuales, especialmente edades, reservas, abonos, mensajes de revisión humana y enlaces. | Matriz de políticas aprobada, fechada y con propietario por documento. |
| Mediano plazo | Realizar un piloto controlado con participantes reclutados y consentimiento informado, inicialmente supervisado por personal. | Número real de participantes; tareas completadas; claridad, utilidad, confianza, rapidez y satisfacción; registro de fallos y escalaciones. |
| Mediano plazo | Definir contrato DTO versionado y autenticación de servicio para la API; proteger el endpoint de chat con controles de identidad y tasa. | Pruebas de autorización, límites, rotación y rechazo de solicitudes no autorizadas. |
| Mediano plazo | Diseñar integración con la plataforma de atención humana y probar el acuse real de creación, tag y estado de lectura antes de prometer transferencia. | Trazas de acuse, recuperación ante fallo, estados y protocolo de operación documentado. |
| Largo plazo | Considerar creación transaccional de reservas solo después de resolver autenticación, consentimiento, idempotencia, conflictos, timeout incierto y confirmación UX. | Pruebas de concurrencia, repetición idempotente y reconciliación con Logic; autorización operativa explícita. |
| Largo plazo | Establecer observabilidad y operación continua: alertas, costos, latencia, actualización documental, evaluación de regresión y auditoría de dependencias. | SLO definidos a partir de mediciones, tendencia de calidad y procedimiento de respuesta a incidentes. |

Las propuestas son actividades futuras y no funcionalidades ya desplegadas.

## 3.10. Conclusiones de la implementación

La implementación materializó una arquitectura modular que combina consulta API, recuperación documental y generación lingüística dentro de un backend con rutas limitadas. Las pruebas automatizadas cubren los principales límites de fuentes, errores de API, recuperación RAG y continuidad conversacional. El dataset repetible aporta mediciones de selección de ruta y fuente para 40 escenarios.

La evidencia demuestra viabilidad técnica del prototipo en el entorno de desarrollo, no eficacia en operación empresarial. La evaluación automática carece de revisión humana, el artefacto histórico no puede asociarse sin reservas con el árbol actual y no se ha realizado un piloto con clientes. La siguiente validación defendible requiere congelar una versión, revisar manualmente las respuestas y medir la experiencia con participantes bajo supervisión. La puesta en producción depende, además, de seguridad API, privacidad, controles de tráfico e integración humana.

# Entregable C. Evidencias y datos que faltan

| Dato no verificable | Evidencia necesaria | Motivo |
|---|---|---|
| Si clientes reales probaron el sistema y cuántos participaron | Confirmación del responsable, protocolo, periodo, perfil general y resultados anonimizados | No hay artefactos de piloto en el repositorio. |
| Calidad factual y relevancia de la corrida de 40 casos | Calificación humana de cada respuesta con la rúbrica definida | El runner dejó 0 casos revisados; las métricas son nulas. |
| Que el `run_id` preservado corresponde al código actual | Nueva evaluación desde commit limpio; conservar diff/hash de fuentes, prompt, dataset, conocimiento y configuración no secreta | El prompt hash difiere y la corrida no capturó estado del árbol de trabajo. |
| Conversaciones manuales como evidencia reproducible | Exportar capturas o transcripciones anonimizadas, fecha, escenario, versión y resultado | Las capturas existen en el historial de conversación, no como corpus versionado de pruebas. |
| Aprobación vigente de políticas y cifras comerciales | Confirmación fechada del negocio para reglas de edad, capacidad, abonos, proceso humano y tarifas operativas | El código permite configuración variable y parte del corpus declara estados abiertos. |
| Entorno y alcance de despliegue | URL/arquitectura del entorno del asistente, controles de acceso, responsable, monitoreo y rollback | No se identificó despliegue del asistente en el repositorio. |
| Base legal y operación de datos personales | Aviso de privacidad, consentimiento u otra base aplicable, acceso, retención, borrado y proveedor/modelo aprobado | El historial puede incluir nombres y teléfonos y se remite al proveedor del modelo. |
| Impacto empresarial | Línea base y mediciones comparables de tiempo de respuesta, tasa de resolución, escalaciones, reservas finalizadas y satisfacción | No existen mediciones previas/posteriores ni datos de operación. |
| Fiabilidad bajo carga y seguridad externa | Prueba de carga, revisión de dependencias, análisis de amenazas y prueba de penetración | No se encontraron esos informes. |

## Referencias internas para verificación

- Contrato y límites de la API: `specs/logic-readonly-interfaces.md`, `config/source-policy.yaml` y `backend/app/logic_api/`.
- Conocimiento y metadatos: `knowledge/INDEX.md`, `knowledge/**/*.md`, `config/knowledge-schema.json` y `backend/app/rag/`.
- Orquestación y flujo: `backend/app/assistant/`, `backend/app/api/` y `agent/nox-system.md`.
- Pruebas: `backend/tests/`.
- Dataset y resultados: `evaluation/cases.json`, `evaluation/results/summary.json`, `evaluation/results/raw_runs.jsonl` y `evaluation/results/release_manifest.json`.
- Criterios y asuntos abiertos: `quality/acceptance-criteria.md` y `quality/unresolved-decisions.md`.
