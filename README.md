# 3D Tolerance Stack-up Tool

Herramienta para análisis de acumulación de tolerancias (tolerance stack-up)
mediante tres métodos: Worst Case, RSS (Root Sum Squares) y Monte Carlo.

Incluye una GUI de escritorio (PySide6) para armar la cadena de dimensiones
y correr los tres métodos sin tocar código.

## Estructura

```
Code/
├── tolstack/
│   ├── __init__.py     # API pública: Stack, Dimension, StackResult, MonteCarloResult
│   ├── models.py       # Dataclasses de datos (sin lógica)
│   └── stack.py        # Lógica de cálculo (clase Stack)
├── examples/
│   └── basic_usage.py  # Ejemplo ejecutable por consola
├── gui/
│   └── app.py           # GUI de escritorio
└── main.py             # Punto de entrada rápido (consola)
```

## Instalación

```bash
git clone https://github.com/JACHmecha/3D-tolerance-stack-up-tool.git
cd 3D-tolerance-stack-up-tool
pip install -r requirements.txt
```

## Uso

### GUI de escritorio

```bash
cd Code
python gui/app.py
```

Tabla editable de dimensiones (nombre, nominal, tol+, tol-, signo), selector de
método y botón de cálculo. Worst Case y RSS muestran el resumen numérico;
Monte Carlo además grafica el histograma de la distribución resultante.

| Worst Case | RSS | Monte Carlo |
|---|---|---|
| ![Worst Case](docs/screenshots/worst_case.png) | ![RSS](docs/screenshots/rss.png) | ![Monte Carlo](docs/screenshots/monte_carlo.png) |

### Por consola

```bash
cd Code
python main.py
python examples/basic_usage.py
```

### Como librería

```python
from tolstack import Stack, Dimension

stack = Stack()
stack.add_dimension(Dimension(name="Base", nominal=25.0, tol_plus=0.10, tol_minus=0.05))
stack.add_dimension(Dimension(name="Bearing", nominal=40.0, tol_plus=0.20, tol_minus=0.10, sign=-1))

stack.summary(method="rss")  # o "worst_case" / "monte_carlo"
```

## Notas de la migración (script único → paquete)

- `method` en `summary()` ahora se normaliza a minúsculas y valida contra
  una lista de métodos permitidos, lanzando `ValueError` si no coincide
  (antes: pasar `"Monte_Carlo"` con mayúsculas producía un `NameError`
  silencioso porque `result` nunca se asignaba).
- El ejemplo de uso se movió a `Code/examples/basic_usage.py`, fuera de la
  librería, para poder importar `tolstack` sin ejecutar código de ejemplo.

## Licencia

Apache License 2.0 — ver [LICENSE](LICENSE).
