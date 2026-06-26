FROM docker.io/library/postgres:16

# pg_uuidv7 is not in the standard postgres:16 image.
# The PGDG APT repository (pre-configured in this base image) provides it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    postgresql-16-pg-uuidv7 \
    && rm -rf /var/lib/apt/lists/*
