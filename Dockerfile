# podiumd-tests with everything a run needs: Python, Chromium (Playwright), kubectl, kubelogin, az and git.
# Build: docker build -t podiumd-tests .
# Run as yourself, so the container reads your kubeconfig and az login (mode 600):
#   docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
#     -v ~/.kube/config:/tmp/kubeconfig:ro -e KUBECONFIG=/tmp/kubeconfig -v ~/.azure:/tmp/.azure \
#     -v "$PWD/results:/opt/podiumd-tests/results" podiumd-tests run --env kees00 --tier smoke
# Add --network host to reach a minikube tunnel. Profiles of another estate: mount them and set
# PODIUMD_TESTS_ENVS_DIR.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

# kubectl within one minor version of the clusters it talks to; kubelogin for AKS with Entra ID.
ARG KUBECTL_VERSION=v1.35.9
ARG KUBELOGIN_VERSION=v0.2.20

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg unzip \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ noble main" \
       > /etc/apt/sources.list.d/azure-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends azure-cli \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && echo "$(curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256")  /usr/local/bin/kubectl" \
       | sha256sum --check \
    && chmod 0755 /usr/local/bin/kubectl \
    && curl -fsSLo /tmp/kubelogin.zip \
       "https://github.com/Azure/kubelogin/releases/download/${KUBELOGIN_VERSION}/kubelogin-linux-amd64.zip" \
    && unzip -j /tmp/kubelogin.zip bin/linux_amd64/kubelogin -d /usr/local/bin \
    && rm /tmp/kubelogin.zip

# Editable: the suite finds tests/, envs/ and perf.yaml next to its sources (config.REPO_ROOT).
COPY --chown=pwuser:pwuser . /opt/podiumd-tests
WORKDIR /opt/podiumd-tests
RUN pip install --no-cache-dir --break-system-packages -e . \
    && python -m playwright install --with-deps chromium

USER pwuser
ENV CI=true PYTEST_ADDOPTS="-p no:cacheprovider"
ENTRYPOINT ["podiumd-tests"]
CMD ["--help"]
