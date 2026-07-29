# Kleiner Updater-Sidecar: führt den Update-Watcher periodisch aus.
# Hat Zugriff auf den Docker-Socket (Rebuild) und das Repo. Der Generator-
# Container selbst bekommt weiterhin KEINEN Docker-/Root-Zugriff.
FROM alpine:3.20

RUN apk add --no-cache docker-cli docker-cli-compose git python3

ENV AIRLOCK_REPO=/repo
WORKDIR /repo

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
