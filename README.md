# 3D Tolerance Stack-up Tool

Herramienta para análisis de acumulación de tolerancias (tolerance stack-up)
mediante tres métodos: Worst Case, RSS (Root Sum Squares) y Monte Carlo.

## Estructura

```
Code/
├── tolstack/
│   ├── __init__.py     # API pública: Stack, Dimension, StackResult, MonteCarloResult
│   ├── models.py       # Dataclasses de datos (sin lógica)
│   └── stack.py        # Lógica de cálculo (clase Stack)
├── examples/
│   └── basic_usage.py  # Ejemplo ejecutable
└── main.py             # Punto de entrada rápido
```

## Uso

Todo el código vive dentro de `Code/`, así que los comandos se ejecutan desde ahí:

```bash
cd Code
python main.py
python examples/basic_usage.py
```

Como librería:

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
