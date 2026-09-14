# Plan de Desarrollo — Executive Chief of Staff (Frontend)

**Rol:** Entrégale este documento a tu asistente de IA de código, fase por fase.

**Visión del Frontend:** Transformar la interfaz de Next.js en un **centro de comando de productividad profesional y diaria**. Brinda acceso inmediato a la agenda del día, detección de huecos de concentración (Deep Work), tarjetas ejecutivas de Standup matutino y tablero de gestión de tareas por proyecto/cliente.

---

## Fase ECS-F0 — Identidad Ejecutiva y Quick Actions Profesionales

**Contexto:**
La pantalla de bienvenida en `components/chat/ChatWindow.tsx` debe ofrecer al usuario profesional los flujos más frecuentes de su día laboral para ahorrar tiempo y guiar la interacción.

**Instrucción para el asistente:**
> 1. Actualiza el branding en `components/navigation/Navbar.tsx` y `components/navigation/Sidebar.tsx`:
>    - Nombre / Título: **"Executive Chief of Staff"** o **"Copiloto Ejecutivo"**.
>    - Subtítulo / Badge: *"Director de Operaciones Personal"*.
> 2. Reemplaza el arreglo `suggestions` en `components/chat/ChatWindow.tsx` con las 4 acciones de alto impacto diario:
>    - ⚡ **Daily Standup:** *"¿Cómo está mi día hoy? Resume mis reuniones, prioridades y horas libres"*
>    - 🎯 **Programar Deep Work:** *"Bloquea 2 horas de trabajo enfocado sin interrupciones en mi calendario"*
>    - 📅 **Auditar Disponibilidad:** *"¿Qué huecos libres tengo hoy para agendar una llamada con un cliente?"*
>    - 📊 **Matriz de Prioridades:** *"Revisa mis tareas pendientes y ordénalas según la Matriz de Eisenhower"*
> 3. Ajusta estilos visuales con estética ejecutiva moderna (tonos oscuros premium, acentos en esmeralda/índigo y bordes interactivos).

**Criterio de aceptación:**
- Al abrir el chat, se presentan las 4 tarjetas ejecutivas y, al hacer clic en cualquiera, se envía la orden de forma fluida.

---

## Fase ECS-F1 — Widget Colapsable de Daily Executive Briefing

**Contexto:**
El backend expone `GET /briefing` (Fase ECS-B3). El usuario debe poder ver el pulso de su día laboral al abrir la app sin necesidad de esperar una respuesta escrita del chat.

**Instrucción para el asistente:**
> 1. Crea `components/briefing/DailyBriefingCard.tsx`:
>    - Realiza fetch a `GET {NEXT_PUBLIC_API_URL}/briefing` con el token JWT de Supabase.
>    - Si Google Calendar no está conectado, muestra un banner amigable con enlace directo a `/settings` para conectar la cuenta.
>    - Renderiza 3 métricas ejecutivas:
>      a) **Clima & Ciudad:** Temperatura y recomendación si hay compromisos fuera de la oficina.
>      b) **Reuniones del Día:** Timeline vertical con las horas de inicio y fin de cada llamada/evento.
>      c) **Foco & Tareas Críticas:** Tareas de alta prioridad que deben resolverse hoy y horas libres detectadas para Deep Work.
> 2. Coloca este componente en la parte superior de `app/(protected)/chat/page.tsx` como una barra colapsable (*"☀️ Resumen Ejecutivo del Día"*).

**Criterio de aceptación:**
- El usuario puede desplegar y ocultar el widget de Briefing con un clic.
- La información de reuniones y tareas críticas se actualiza en tiempo real.

---

## Fase ECS-F2 — Tarjeta de Bloqueo de Deep Work en el Chat (`DeepWorkCard`)

**Contexto:**
Cuando el agente agenda un bloque de concentración en Google Calendar mediante `schedule_deep_work`, la UI debe presentar una tarjeta visual de confirmación con detalles del evento.

**Instrucción para el asistente:**
> 1. Crea `components/chat/DeepWorkCard.tsx`:
>    - Muestra: Proyecto asociado, descripción del bloque de trabajo, horario reservado (ej. *"10:30 AM - 12:30 PM (2h)"*) y badge de confirmación en Google Calendar.
>    - Enlace directo al evento en Google Calendar web (`https://calendar.google.com`).
> 2. Integra el renderizado de este componente dentro de `MessageBubble.tsx` cuando la respuesta del agente confirme la ejecución de `schedule_deep_work`.

**Criterio de aceptación:**
- Al pedir agendar un bloque de enfoque, la respuesta incluye la tarjeta visual formateada con botón de apertura en Google Calendar.

---

## Fase ECS-F3 — Tablero de Proyectos y Tareas Diarias (`/projects` o `/tasks`)

**Contexto:**
Un profesional necesita visualizar y filtrar sus compromisos por cliente o proyecto sin requerir interacción por chat en cada momento.

**Instrucción para el asistente:**
> 1. Crea `app/(protected)/projects/page.tsx`:
>    - Vista en formato tablero o lista agrupada por Proyecto (`project`) o Prioridad (`high`, `medium`, `low`).
>    - Permite marcar tareas como completadas (tachado interactivo) o eliminarlas.
>    - Indicador de sincronización con Google Calendar para tareas con fecha límite.
> 2. Agrega el acceso a "Proyectos & Tareas" en `Sidebar.tsx` con icono `Briefcase` o `CheckCircle2`.

**Criterio de aceptación:**
- El usuario puede navegar a `/projects`, ver sus pendientes organizados por proyecto y gestionar su estado con feedback inmediato.

---

## Fase ECS-F4 — Pulido Ejecutivo, Responsive y Modo Audio (Opcional)

**Instrucción para el asistente:**
> 1. Revisa la adaptación en dispositivos móviles (la interfaz debe sentirse como una app ejecutiva de bolsillo).
> 2. Añade un botón de reproducción de audio usando la Web Speech API nativa del navegador (`window.speechSynthesis`) para poder escuchar el Daily Standup mientras se conduce o se toma un café por la mañana.
> 3. Ejecuta `npm run build` para asegurar compilación limpia en Next.js sin errores de TypeScript.

**Criterio de aceptación:**
- Compilación de producción exitosa en Next.js.
- Interfaz completamente responsive y fluida en escritorio y móvil.

---

## Resumen de Fases y Dependencias (Frontend)

| Fase | Descripción | Dependencias |
|---|---|---|
| **ECS-F0** | Identidad ejecutiva + Quick Actions profesionales | — |
| **ECS-F1** | Widget colapsable de Daily Executive Briefing | Backend Fase ECS-B3 |
| **ECS-F2** | Tarjeta visual `DeepWorkCard` en el chat | Backend Fase ECS-B2 |
| **ECS-F3** | Tablero de Proyectos & Tareas (`/projects`) | Backend Fase ECS-B0 |
| **ECS-F4** | Pulido UX, responsive y síntesis de voz matutina | ECS-F0 a ECS-F3 |
