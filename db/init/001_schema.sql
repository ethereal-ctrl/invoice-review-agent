-- Schema gemäß docs/spezifikation.md, Abschnitt 2.
-- erp:   Legacy-Stammdaten und Belege (Agent: nur lesen)
-- app:   Fälle, Queue, Entscheidungen (Agent: lesen und schreiben)
-- audit: append-only Protokoll (Agent: nur einfügen)

CREATE SCHEMA erp;
CREATE SCHEMA app;
CREATE SCHEMA audit;

-- ---------------------------------------------------------------- erp

CREATE TABLE erp.kred_stamm (
    kred_nr   text PRIMARY KEY,
    name      text    NOT NULL,
    ust_id    text    NOT NULL UNIQUE,
    iban      text    NOT NULL,
    gesperrt  boolean NOT NULL DEFAULT false
);

CREATE TABLE erp.mat_stamm (
    mat_nr         text PRIMARY KEY,
    bezeichnung    text         NOT NULL,
    basis_einheit  text         NOT NULL DEFAULT 'ST',
    ust_satz       numeric(4,2) NOT NULL CHECK (ust_satz IN (7.00, 19.00))
);

CREATE TABLE erp.mat_einh (
    mat_nr   text    NOT NULL REFERENCES erp.mat_stamm,
    einheit  text    NOT NULL,
    faktor   integer NOT NULL CHECK (faktor > 0),
    PRIMARY KEY (mat_nr, einheit)
);

CREATE TABLE erp.best_kopf (
    best_nr   text PRIMARY KEY,
    kred_nr   text    NOT NULL REFERENCES erp.kred_stamm,
    datum     date    NOT NULL,
    waehrung  char(3) NOT NULL DEFAULT 'EUR' CHECK (waehrung = 'EUR')
);

CREATE TABLE erp.best_pos (
    best_nr      text          NOT NULL REFERENCES erp.best_kopf,
    pos          integer       NOT NULL,
    mat_nr       text          NOT NULL REFERENCES erp.mat_stamm,
    menge        integer       NOT NULL CHECK (menge > 0),       -- Basiseinheit
    preis_netto  numeric(12,4) NOT NULL CHECK (preis_netto >= 0), -- pro Basiseinheit
    PRIMARY KEY (best_nr, pos)
);

CREATE TABLE erp.we_pos (
    we_nr            text    NOT NULL,
    best_nr          text    NOT NULL,
    pos              integer NOT NULL,
    menge_geliefert  integer NOT NULL CHECK (menge_geliefert > 0), -- Basiseinheit
    datum            date    NOT NULL,
    PRIMARY KEY (we_nr, best_nr, pos),
    FOREIGN KEY (best_nr, pos) REFERENCES erp.best_pos
);

CREATE TABLE erp.re_hist (
    kred_nr        text          NOT NULL REFERENCES erp.kred_stamm,
    re_nr          text          NOT NULL,
    best_nr        text          NOT NULL REFERENCES erp.best_kopf,
    betrag_brutto  numeric(12,2) NOT NULL,
    datum          date          NOT NULL,
    PRIMARY KEY (kred_nr, re_nr)
);

-- R13 braucht die bereits berechnete Menge pro Bestellposition.
CREATE TABLE erp.re_hist_pos (
    kred_nr          text    NOT NULL,
    re_nr            text    NOT NULL,
    best_nr          text    NOT NULL,
    pos              integer NOT NULL,
    menge_berechnet  integer NOT NULL CHECK (menge_berechnet > 0), -- Basiseinheit
    PRIMARY KEY (kred_nr, re_nr, best_nr, pos),
    FOREIGN KEY (kred_nr, re_nr) REFERENCES erp.re_hist,
    FOREIGN KEY (best_nr, pos)   REFERENCES erp.best_pos
);

-- ---------------------------------------------------------------- app

CREATE TABLE app.faelle (
    fall_id    text PRIMARY KEY,
    pdf_pfad   text        NOT NULL,
    status     text        NOT NULL DEFAULT 'offen'
               CHECK (status IN ('offen', 'in_arbeit', 'erledigt', 'fehler')),
    locked_at  timestamptz,
    versuche   integer     NOT NULL DEFAULT 0,
    erstellt   timestamptz NOT NULL DEFAULT now()
);

-- Queue: SELECT ... FROM app.faelle WHERE status = 'offen' FOR UPDATE SKIP LOCKED
CREATE INDEX faelle_offen ON app.faelle (erstellt) WHERE status = 'offen';

CREATE TABLE app.entscheidungen (
    id            bigserial PRIMARY KEY,
    fall_id       text        NOT NULL REFERENCES app.faelle,
    run_id        text        NOT NULL,
    stufe         text        NOT NULL,
    entscheidung  text        NOT NULL
                  CHECK (entscheidung IN ('FREIGEBEN', 'ZURUECKHALTEN', 'ESKALIEREN')),
    grund_codes   text[]      NOT NULL DEFAULT '{}',
    tokens_ein    integer,
    tokens_aus    integer,
    erstellt      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fall_id, run_id)
);

-- ---------------------------------------------------------------- audit

CREATE TABLE audit.ereignisse (
    id                bigserial PRIMARY KEY,
    ts                timestamptz NOT NULL DEFAULT now(),
    run_id            text        NOT NULL,
    fall_id           text,
    knoten            text        NOT NULL,
    tool              text,
    args_geschwaerzt  jsonb,
    policy_regel      text,
    ergebnis          text        NOT NULL,
    modell            text,
    tokens_ein        integer,
    tokens_aus        integer
);

CREATE FUNCTION audit.verbiete_aenderung() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.ereignisse ist append-only (% verboten)', TG_OP;
END;
$$;

CREATE TRIGGER ereignisse_append_only
    BEFORE UPDATE OR DELETE ON audit.ereignisse
    FOR EACH ROW EXECUTE FUNCTION audit.verbiete_aenderung();

CREATE TRIGGER ereignisse_kein_truncate
    BEFORE TRUNCATE ON audit.ereignisse
    FOR EACH STATEMENT EXECUTE FUNCTION audit.verbiete_aenderung();
