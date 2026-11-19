#!/bin/sh
# Freigabe durch Menschen: Status, Freigabe-Tabelle, Schema für LangGraph-Checkpoints,
# Rolle ia_mensch für das Freigabe-Cockpit. Idempotent, darf auf bestehenden Datenbanken laufen.
set -eu

psql -v ON_ERROR_STOP=1 -v mensch_pw="${IA_MENSCH_PASSWORD:?IA_MENSCH_PASSWORD fehlt}" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
ALTER TABLE app.faelle DROP CONSTRAINT IF EXISTS faelle_status_check;
ALTER TABLE app.faelle ADD CONSTRAINT faelle_status_check
    CHECK (status IN ('offen', 'in_arbeit', 'wartet_auf_mensch', 'erledigt', 'fehler'));

-- Ein Fall, den die Policy einem Menschen vorgelegt hat (Kompetenzgrenze R15).
CREATE TABLE IF NOT EXISTS app.freigaben (
    fall_id          text PRIMARY KEY REFERENCES app.faelle,
    run_id           text        NOT NULL,
    stufe            text        NOT NULL,
    thread_id        text,                    -- LangGraph-Thread zum Fortsetzen (nur Agent)
    vorschlag        text        NOT NULL,
    policy_regel     text,
    brutto           numeric(12,2),
    grund_codes      text[]      NOT NULL DEFAULT '{}',
    erstellt         timestamptz NOT NULL DEFAULT now(),
    entschieden_von  text,
    entschieden_am   timestamptz,
    ergebnis         text
);
ALTER TABLE app.freigaben DROP CONSTRAINT IF EXISTS freigaben_ergebnis_check;
ALTER TABLE app.freigaben ADD CONSTRAINT freigaben_ergebnis_check
    CHECK (ergebnis IN ('FREIGEBEN', 'ZURUECKHALTEN'));
GRANT SELECT, INSERT, UPDATE, DELETE ON app.freigaben TO ia_agent;

-- Checkpoints des LangGraph-Agenten (Tabellen legt der Checkpointer selbst an).
CREATE SCHEMA IF NOT EXISTS lg;
GRANT USAGE, CREATE ON SCHEMA lg TO ia_agent;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ia_mensch') THEN
        CREATE ROLE ia_mensch LOGIN;
    END IF;
END
$$;
ALTER ROLE ia_mensch PASSWORD :'mensch_pw';

-- Sachbearbeitung: alles lesen (auch das Protokoll), über Freigaben entscheiden,
-- Protokoll nur ergänzen, ERP nie ändern.
GRANT USAGE ON SCHEMA erp, app, audit, lg TO ia_mensch;
GRANT SELECT ON ALL TABLES IN SCHEMA erp TO ia_mensch;
GRANT SELECT ON ALL TABLES IN SCHEMA app TO ia_mensch;
GRANT UPDATE ON app.faelle, app.freigaben TO ia_mensch;
GRANT INSERT ON app.entscheidungen TO ia_mensch;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO ia_mensch;
GRANT SELECT, INSERT ON audit.ereignisse TO ia_mensch;
GRANT USAGE ON SEQUENCE audit.ereignisse_id_seq TO ia_mensch;
ALTER DEFAULT PRIVILEGES FOR ROLE ia_agent IN SCHEMA lg
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ia_mensch;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lg TO ia_mensch;
SQL
