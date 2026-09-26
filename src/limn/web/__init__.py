"""The HTTP layer: the request handler, the answers it gives for each outcome, and the errors it renders.

The package is named web, not http: server.py runs as a file (python .../limn/server.py, how instances start), which
puts limn/ itself first on sys.path, and a limn/http package would then shadow the standard library's http.server.

Nothing here imports server.py. The composition root (server.py) binds the handler to the services it calls through
limn.web.app.App; server.py imports the error types from here, the direction the handbook's target structure keeps
(docs/handbook/architecture.md §목표 구조).
"""
