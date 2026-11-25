"""Point d'entrée Phusion Passenger pour l'hébergement cPanel (o2switch).

Convertit l'application ASGI FastAPI (src.main.app) en application WSGI
compatible avec Apache Passenger via a2wsgi.
"""

import os
import sys

# Ajout du répertoire courant au PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from a2wsgi import ASGIMiddleware

    from src.main import app

    application = ASGIMiddleware(app)
except ImportError:
    # Si a2wsgi n'est pas encore installé, exposition directe de l'application ASGI
    from src.main import app as application  # noqa: F401

__all__ = ["application"]

