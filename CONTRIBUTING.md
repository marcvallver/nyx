# Contribuir a Nyx

Proyecto temprano y muy ligado a un setup concreto (KDE Plasma 6 / Wayland / NVIDIA). Issues y PRs
bienvenidos, sobre todo de portabilidad (otros compositores wlroots, otras distros).

## Entorno

```bash
pip install -e ".[dev]"   # pytest + ruff
ruff check .
ruff format .
pytest -q
```

## Principios

- **La lógica pura no importa GTK.** Módulos como `streamparse.py` y (futuro) `policy.py` deben
  poder probarse sin un display ni PyGObject — así corren en CI. La GUI va aparte.
- **Seguridad primero.** El asistente es agéntico con confirmación: cualquier acción mutadora pasa
  por la capa de política y, en la zona gris, por confirmación explícita del usuario. Nunca un clic
  para operaciones destructivas.
- **Nada con copyright en el repo.** Sin sprites/sonidos de terceros; el avatar por defecto es el orbe.
- **Posición relativa.** Las superficies se anclan con bordes+márgenes (layer-shell), no con píxeles
  absolutos, para no acoplarse a una resolución/escala concreta.

## Estilo

- Python ≥ 3.11, `ruff` (lint + format), line-length 100.
- Mensajes de commit en presente y descriptivos; conventional-commits opcional.
