# Guía para ti — Cuentas, accesos y tareas que debes preparar

Esta guía contiene las acciones que requieren tu intervención como propietario del proyecto o de Logic Escape Room.

## 1. Repositorio Git

### Necesitas

Una cuenta de GitHub si todavía no tienes una disponible para este proyecto.

### Crear

Un repositorio privado, por ejemplo:

`logic-ai-assistant-pfm`

### No subir

- `.env`;
- claves;
- tokens;
- datos personales reales;
- conversaciones sin anonimizar.

### Tú debes hacer

- crear el repositorio;
- dar acceso sólo a quien lo necesite;
- clonar o abrir el repositorio donde usarás Codex.

---

## 2. OpenAI API

La suscripción de ChatGPT y el uso programático de la API son servicios separados.

Para que el prototipo llame al LLM necesitas acceso a la OpenAI API Platform.

### Debes preparar

1. Acceder a la plataforma de OpenAI.
2. Tener facturación habilitada para API.
3. Crear un proyecto específico, por ejemplo:
   - `logic-escape-room-pfm`
4. Crear una clave de API dentro de ese proyecto.
5. Guardarla de forma segura.
6. Revisar límites/presupuesto del proyecto.

### En tu computador

La clave va en `.env`:

```env
OPENAI_API_KEY=...
```

Nunca la pegues en:

- `AGENTS.md`;
- prompts;
- código;
- GitHub;
- screenshots;
- documentación del PFM.

### Modelo

No necesitas fijarlo para siempre.

El proyecto usará:

```env
OPENAI_MODEL=...
```

para poder cambiarlo sin tocar lógica de negocio.

---

## 3. API de Logic Escape Room

### Ya tienes

La documentación de la API pública del asistente.

### Necesitas confirmar

Una URL base válida para desarrollo.

Idealmente:

- staging/pruebas, o
- backend local con datos ficticios.

Configúrala localmente:

```env
LOGIC_API_BASE_URL=https://...
```

No escribas esa URL directamente en el código.

### Muy importante

Las rutas documentadas actualmente no usan autenticación servidor-a-servidor.

Para el PFM podemos integrar las rutas de lectura desde el backend del asistente.

Para producción real, debe agregarse autenticación y protección de carga.

### Tú debes confirmar durante Fase 2

La respuesta real de:

- `/api/rates`
- `/api/rooms`
- `/api/bookings/opening-hours`
- `/api/bookings/quote`
- `/api/bookings/availability`

Especialmente necesitamos revisar los nombres exactos de los campos reales de `/api/rooms`, porque el contrato actual está acoplado al esquema de base de datos.

---

## 4. No necesitas cuenta para Chroma

Para el MVP utilizaremos Chroma local.

No necesitas crear cuenta en:

- Pinecone;
- Weaviate Cloud;
- Qdrant Cloud;
- otra base vectorial administrada.

---

## 5. No necesitas cuenta para LangChain

Inicialmente no usaremos LangChain como dependencia principal.

La idea es mantener:

- OpenAI SDK;
- Python;
- FastAPI;
- Chroma.

Sólo se agregaría si aparece una necesidad concreta.

---

## 6. Preparar el conocimiento que irá al RAG

Esta es una de las tareas más importantes que dependen de ti.

Necesitamos convertir el conocimiento operativo que hoy está en tu cabeza o en la del personal en reglas explícitas.

### Capacidad

Documenta:

- cuándo se puede superar el máximo estándar;
- en qué salas;
- cuánto se puede superar;
- qué edades/condiciones aplican;
- cuándo NO se permite.

### Edades

Documenta:

- qué significa exactamente la edad mínima del sistema;
- qué pasa si el menor va acompañado;
- qué salas tienen excepciones.

### Casos especiales

Revisa si existen reglas para:

- embarazadas;
- movilidad reducida;
- grupos escolares;
- cumpleaños;
- niños pequeños;
- grupos mayores al máximo;
- llegada tarde;
- cambios de horario;
- otros casos frecuentes.

No inventaremos estas reglas.

Tú debes confirmar cuáles son reales.

### Formato simple

Puedes entregarlas así:

```text
CASO:
7 niños de 12 años quieren Portal.

REGLA NORMAL:
Máximo 6.

EXCEPCIÓN:
...

CONDICIONES:
...

NO APLICA:
...

SI HAY DUDA:
Preguntar al personal.
```

Luego se convierten en Markdown estructurado para RAG.

---

## 7. Preparar preguntas reales para evaluación

Más adelante necesitaremos aproximadamente 40 casos.

Guarda ejemplos reales de preguntas que llegan por WhatsApp.

No guardes:

- nombres;
- teléfonos;
- documentos;
- datos de pago.

Sólo el texto anonimizado.

Ejemplos:

- “Somos 5, ¿cuánto vale el sábado?”
- “¿Portal está libre mañana a las 7?”
- “Mi hijo tiene 10 y va conmigo, ¿puede entrar?”
- “Somos 7 niños de 12, ¿pueden jugar Portal?”

---

## 8. Software local

### Obligatorio

- Git
- Python 3.12 o superior
- Node.js 20 o superior
- editor/IDE desde el que usarás Codex

### Recomendado

- VS Code
- Postman o Bruno para pruebas HTTP si lo necesitas

No es obligatorio crear cuenta en Postman.

---

## 9. Cuentas que no necesitas por ahora

No crees cuentas todavía en:

- Vercel;
- Render;
- Railway;
- AWS;
- Azure;
- Google Cloud;
- Pinecone;
- Redis Cloud;
- LangSmith.

Ninguna es necesaria para demostrar el MVP local.

---

## 10. Checklist antes de Fase 1

- [ ] Repositorio privado creado.
- [ ] Documentación de este paquete copiada al repo.
- [ ] `AGENTS.md` en la raíz.
- [ ] OpenAI API disponible.
- [ ] Proyecto de OpenAI API creado.
- [ ] Clave de API guardada.
- [ ] Facturación/límite de gasto revisado.
- [ ] URL del API de Logic identificada.
- [ ] Python instalado.
- [ ] Node.js instalado.
- [ ] Git instalado.

## 11. Checklist antes de Fase 3

- [ ] Inventario de excepciones del negocio.
- [ ] Reglas especiales por edad.
- [ ] Reglas especiales por capacidad.
- [ ] Casos que siempre escalan a una persona.
- [ ] FAQs no disponibles en la API.

## 12. Checklist antes de evaluación

- [ ] 30–40 preguntas reales o simuladas.
- [ ] Sin datos personales.
- [ ] Casos normales.
- [ ] Casos ambiguos.
- [ ] Casos especiales.
- [ ] Casos de escalamiento.
- [ ] Casos de disponibilidad.
- [ ] Casos de cotización.

## 13. Cómo trabajar con Codex

No le pidas:

> Haz todo el proyecto.

Trabaja por fases.

Ejemplo:

> Lee AGENTS.md y docs/01_PHASE_BOOTSTRAP.md. Implementa únicamente la Fase 1. No avances a la Fase 2. Ejecuta pruebas y dime qué archivos cambiaste y qué queda pendiente.

Luego:

> Lee AGENTS.md y docs/02_PHASE_LOGIC_API.md. Implementa la Fase 2 usando el contrato real. No inventes campos de /api/rooms; si la respuesta real no coincide, detente y muéstrame la diferencia.

Este enfoque reduce mucho el riesgo de que Codex construya sobre supuestos incorrectos.
