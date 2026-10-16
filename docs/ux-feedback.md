# Pipeline inicial de feedback de UX

Este piloto convierte el recorrido **crear una cadena → analizar → revisar → editar → volver a analizar → corregir un error** en un informe reproducible con capturas. Usa datos sintéticos y la aplicación PySide6/Qt Widgets en modo offscreen. El resultado sirve para detectar regresiones del recorrido y preparar una revisión visual.

Es la primera etapa de la [propuesta de feedback automático](proposal-automated-ux-feedback-2026-10-15.md). La revisión mediante IA, la exploración autónoma y los avisos programados siguen pendientes. El piloto no envía datos a servicios externos.

## Ejecutar localmente

Desde la raíz del checkout, con Python 3.10 o posterior y las dependencias de escritorio instaladas. CI usa Python 3.12:

```powershell
python -m pip install -r requirements.txt .
$env:QT_QPA_PLATFORM = 'offscreen'
python scripts/run_ux_feedback.py --output-dir ux-evidence
```

El comando imprime `Informe UX: <ruta absoluta>/report.html`. Cada ejecución crea su propia carpeta dentro del directorio indicado y recorre dos tamaños: **1300 × 800** y **1024 × 768**. Si se omite `--output-dir`, guarda la evidencia en `artifacts/ux-feedback` dentro del checkout. Los controles reciben clics y teclado de Qt; las comprobaciones pueden leer el estado y los resultados para contrastarlos con referencias independientes.

Para seleccionar tamaños y ajustar el límite de ejecución de cada ventana:

```powershell
python scripts/run_ux_feedback.py --size 1300x800 --size 1024x768 --timeout 90
```

`--size` se puede repetir; admite ancho de **1024 a 3840** y alto de **768 a 2160** píxeles lógicos. `--timeout` admite **10–180 segundos** por ventana y su valor predeterminado es **60**. `--repeat` admite **1–10** repeticiones de la matriz completa. Un tiempo agotado se registra como fallo del corredor; no como defecto confirmado de TolForge.

Para comprobar la estabilidad del piloto:

```powershell
python scripts/run_ux_feedback.py --output-dir ux-evidence --repeat 5
```

Para comprobar que el informe conserva un fallo deliberado y su evidencia:

```powershell
python scripts/run_ux_feedback.py --output-dir ux-evidence --inject-failure
```

`--repeat 5` ejecuta ambos tamaños cinco veces, diez configuraciones en total. La ejecución con `--inject-failure` debe terminar con código **1**. El diagnóstico introducido no representa un defecto real del producto y debe leerse como tal. Las cinco repeticiones estables y el diagnóstico son el umbral inicial para aceptar el corredor; no demuestran ausencia de intermitencia.

## Cobertura del primer corte

| Recorrido | Qué comprueba |
| --- | --- |
| U01: crear y analizar | Introducir las dimensiones, sus signos y tolerancias; obtener el resultado Worst Case y conservar evidencia de la interfaz. |
| U02: revisar el criterio funcional | Contrastar la banda del resultado con el intervalo funcional [0.9, 1.1] mm y distinguirla del ajuste respecto de cero. |
| U06, tramo inicial | Editar una tolerancia, comprobar que el resultado anterior deja de estar vigente y se bloquea su exportación, recalcular, introducir un valor inválido, observar el aviso y recuperarse mediante corrección. |

El fixture usa Housing de **10 ± 0.2 mm** con signo positivo y Pin de **9 ± 0.1 mm** con signo negativo. La referencia Worst Case es nominal **1 mm** y extremos **[0.7, 1.3] mm**, calculados fuera del servicio de análisis de TolForge. Las contribuciones de varianza son **80% / 20%**. Reducir Housing a **±0.1 mm** produce **[0.8, 1.2] mm** y contribuciones **50% / 50%**. Ambas bandas exceden el intervalo funcional; ninguna implica interferencia respecto de cero.

El piloto cubre el flujo escalar. El renderizador CAD está deshabilitado: no califica el viewport nativo, STEP/OpenCASCADE ni el ejecutable empaquetado. Tampoco cubre RSS, Monte Carlo, guardar/reabrir/exportar mediante diálogos, escalado de Windows ni descubrimiento de controles por una persona o un agente. Los tamaños offscreen permiten inspeccionar presentación y recortes, sin demostrar comportamiento de una sesión interactiva de Windows.

## Leer el feedback

| Archivo | Para qué sirve |
| --- | --- |
| `summary.md` | Leer el resultado y los hallazgos principales en pocos minutos. |
| `report.html` | Abrir el informe local y seguir la evidencia de los pasos y las capturas. |
| `run.json` | Inspeccionar los datos estructurados de la ejecución, sus comprobaciones y entorno. |
| Capturas | Ver los hitos del recorrido y la evidencia del fallo cuando está disponible. |
| `review-prompt.md` | Preparar una revisión visual posterior con contexto, límites y criterios. No demuestra que se haya realizado una revisión con IA. |

Conservar la carpeta completa al compartir o mover un informe para mantener sus enlaces a las capturas. Los artefactos describen la revisión y las condiciones en que se obtuvieron; un resultado histórico no valida cambios posteriores.

Las conclusiones se separan por evidencia:

- **Defecto reproducido** (`defect_reproduced`): una comprobación objetiva del resultado o del estado visible falla durante el recorrido.
- **Hipótesis de UX** (`ux_hypothesis`): una observación de presentación o comprensión que requiere revisión; un aprobado numérico no la descarta. El piloto prepara la evidencia para esta revisión y no genera por sí solo conclusiones de comprensión humana.
- **Infraestructura o corredor** (`infrastructure` / `runner_error`): falta una dependencia, no se puede preparar el entorno o la automatización no logra operar un control. No cuenta como un aprobado del producto.

Los estados del informe son `pass`, `product_failure`, `runner_error` e `infrastructure_unavailable`. Los códigos de salida permiten integrarlos: **0** indica que las comprobaciones del recorrido pasan, **1** indica un fallo de producto detectado por una comprobación (o el diagnóstico deliberado) y **2** indica un fallo del corredor o su infraestructura. Un fallo debe investigarse junto con su paso, esperado/observado y evidencia; un reintento que pase no borra el primer informe.

Una persona puede comenzar la revisión abriendo `report.html` y las capturas del tamaño menor, y luego usar `review-prompt.md` para buscar etiquetas ambiguas, unidades poco claras, estados obsoletos y contenido recortado. Las acciones y tiempos de un guion son datos técnicos del recorrido; no miden satisfacción ni velocidad de usuarios reales.

## Recibirlo en GitHub Actions

El workflow [UX feedback pilot](../.github/workflows/ux-feedback.yml) se ejecuta en PR y cambios a `main` que afecten código, scripts, pruebas o dependencias relevantes; también admite ejecución manual desde Actions. Usa Windows y Python 3.12 con Qt offscreen.

Para consultar una ejecución:

1. Abrir **Actions → UX feedback pilot → la ejecución**.
2. Leer su resumen, que incorpora los `summary.md` generados incluso si falla el recorrido.
3. Descargar el artefacto `ux-feedback-<run_id>-<attempt>` y abrir el informe HTML de cada carpeta de ejecución. Los artefactos se conservan 14 días.

Si falla la instalación o el proceso se detiene antes de generar un informe, el resumen indica que no hay evidencia de aprobado; los logs de Actions son la fuente para diagnosticarlo. La carga del artefacto se intenta también cuando hay fallos, con lo que exista en el directorio de evidencia.

Este corte no crea un calendario, comentarios automáticos en PR ni notificaciones externas. La disponibilidad del workflow en GitHub requiere incorporar y subir los cambios al repositorio.

## Siguiente etapa

Completar U03–U05 y los diálogos reales de U06; añadir revisión de capturas, comparación con una base compatible y deduplicación de hallazgos. Después, conectar una entrega de avisos con enlaces al informe y validar el control de una sesión interactiva antes de afirmar que existe exploración autónoma. Mantener separados los defectos reproducibles y las propuestas de diseño hasta seleccionar qué mejoras implementar.

## Verificación registrada — 2026-10-15

La implementación local basada en `main` `80c4e44` pasó **120 pruebas** relacionadas
con el corredor, los informes y los contratos existentes de análisis, tarjetas,
tabla y navegación. El código nuevo permanecía sin commit durante estas pruebas.

La matriz final ejecutó cinco repeticiones de cada tamaño: **10 configuraciones,
100 pasos y 100 capturas**, todas aprobadas. Se comprobaron el tamaño real, escala
1 y hashes de los archivos al principio/final. Los avisos se verifican por título
y contenido: fila/campo/requisito numérico para el dato inválido, e instrucciones
de recalcular antes de exportar para un informe obsoleto. Las capturas se
inspeccionaron visualmente; el renderizador estaba desactivado.

Evidencia local ignorada por Git: ejecución
`artifacts/ux-feedback/20261016T035215.040856Z-a79fe943ff18/`.
Una ejecución separada con `--inject-failure --size 1024x768` terminó con código 1
y conservó tres pasos/capturas con la advertencia de diagnóstico, bajo
`artifacts/ux-feedback/20261016T035215.121876Z-9a85c2f0dfc5/`.
El fallo se produjo cambiando una expectativa del verificador; no es un defecto
observado de TolForge.

Entorno de estas ejecuciones: Windows, Python 3.10.0, PySide6/Qt 6.11.1, Qt
offscreen y factor 1. Los informes contienen los hashes de los archivos realmente
evaluados. GitHub Actions/Python 3.12 está configurado, pero no se ejecutó en un
host remoto durante esta tarea. Tampoco se reconstruyó ni calificó un ejecutable
empaquetado.
