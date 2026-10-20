"""ZGW Office add-in: the manifests Office loads and the backend behind the frontend."""

# Served by the frontend; Office loads the add-in from them.
MANIFESTS = ("/manifest-office.xml", "/manifest-outlook.xml")
# The URL in the manifests until the frontend's start script replaces it with common.frontendUrl.
UNREPLACED_URL = "localhost:3000"
# Where the frontend passes requests on to the backend.
BACKEND = "/proxy"
