import os

# Permite correr os testes de interface sem abrir janelas (e em CI sem ecra).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
