"""Register the bundled CAD runtime and Windows ICU before Qt runtime hooks."""
from gui.runtime import configure_native_runtime

configure_native_runtime()
