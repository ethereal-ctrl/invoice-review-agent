#!/bin/sh
# Rolle für den Agenten: erp nur lesen, app lesen/schreiben, audit nur einfügen.
set -eu

psql -v ON_ERROR_STOP=1 -v agent_pw="${IA_AGENT_PASSWORD:?IA_AGENT_PASSWORD fehlt}" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE ia_agent LOGIN PASSWORD :'agent_pw';

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA erp, app, audit TO ia_agent;

GRANT SELECT ON ALL TABLES IN SCHEMA erp TO ia_agent;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA app TO ia_agent;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO ia_agent;

-- Nur INSERT, kein SELECT: Der Agent kann das Protokoll weder lesen noch ändern.
GRANT INSERT ON audit.ereignisse TO ia_agent;
GRANT USAGE ON SEQUENCE audit.ereignisse_id_seq TO ia_agent;
SQL
