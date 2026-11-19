"""Freigabe-Cockpit: Übersicht, Fall mit Spur des Agenten, Entscheidung, Audit-Log.

Läuft als Rolle `ia_mensch` (alles lesen, über Freigaben entscheiden, ERP nie ändern).
Serverseitig gerenderte Seiten mit HTMX für die Entscheidung, ohne Build-Schritt.
Gold-Labels sieht das Cockpit nie: Es zeigt nur, was auch im Betrieb vorhanden wäre.
Bewusst ohne Login: Der Name der entscheidenden Person wird eingetragen (nur lokal).
"""

import json
import threading
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from psycopg.rows import dict_row

from invoice_agent import mensch, queue
from invoice_agent.audit import SpeicherAudit
from invoice_agent.config import Settings

VORLAGEN = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Lesbares JSON mit Umlauten; Jinja escaped die Ausgabe weiterhin (Autoescape).
VORLAGEN.env.filters["json"] = lambda wert: json.dumps(wert, ensure_ascii=False)  # pyright: ignore[reportUnknownLambdaType]
LADDER = ("b0", "b1", "regeln", "llm:nim_gross", "agent:nim_gross")


def _kennzahlen(runs: Path, split: str = "dev") -> list[dict[str, Any]]:
    """Letzter Lauf je Stufe auf dem Split (nur Metriken, keine Gold-Daten)."""
    zeilen: list[dict[str, Any]] = []
    for stufe in LADDER:
        laeufe = sorted(runs.glob(f"{stufe}_{split}_*/metriken.json"))
        if not laeufe:
            continue
        m = json.loads(laeufe[-1].read_text(encoding="utf-8"))
        zeilen.append({"stufe": stufe, "lauf": laeufe[-1].parent.name, **m})
    return zeilen


class _Fortsetzer:
    """Baut pro Agent-Stufe einmal eine Instanz mit Postgres-Checkpointer (Replay-Modus:
    beim Fortsetzen ruft der Graph kein LLM mehr auf)."""

    def __init__(self, dsn: str, settings: Settings) -> None:
        self._dsn = dsn
        self._settings = settings
        self._stufen: dict[str, Any] = {}
        self._lock = threading.Lock()

    def __call__(self, stufe: str, thread_id: str, freigeben: bool) -> None:
        from invoice_agent.checkpoint import postgres_checkpointer
        from invoice_agent.eval.runner import baue_stufe

        with self._lock:
            if stufe not in self._stufen:
                with psycopg.connect(self._dsn) as conn:
                    welt = queue.lies_welt(conn)
                saver, _ = postgres_checkpointer(self._dsn)
                self._stufen[stufe] = baue_stufe(
                    stufe, self._settings, welt, "replay", SpeicherAudit(), "cockpit",
                    checkpointer=saver,
                )  # fmt: skip
            self._stufen[stufe].fortsetzen(thread_id, freigeben)


def erstelle_app(dsn: str, settings: Settings, daten: Path, runs: Path) -> FastAPI:
    app = FastAPI(title="Freigabe-Cockpit", docs_url=None, redoc_url=None)
    fortsetzen = _Fortsetzer(dsn, settings)

    def verbindung() -> psycopg.Connection[Any]:
        return psycopg.connect(dsn)

    def alle(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, params).fetchall()  # pyright: ignore[reportArgumentType]

    @app.get("/", response_class=HTMLResponse)
    def uebersicht(request: Request) -> Response:
        with verbindung() as conn:
            status = dict(
                conn.execute("SELECT status, count(*) FROM app.faelle GROUP BY status").fetchall()
            )
            offene = mensch.offene(conn)
            letzte = alle(
                conn,
                "SELECT fall_id, stufe, entscheidung, grund_codes, erstellt "
                "FROM app.entscheidungen ORDER BY erstellt DESC, id DESC LIMIT 15",
            )
        return VORLAGEN.TemplateResponse(
            request,
            "uebersicht.html",
            {"status": status, "offene": offene, "letzte": letzte, "ladder": _kennzahlen(runs)},
        )

    @app.get("/fall/{fall_id}", response_class=HTMLResponse)
    def fall(request: Request, fall_id: str) -> Response:
        with verbindung() as conn:
            kopf = alle(conn, "SELECT * FROM app.faelle WHERE fall_id = %s", (fall_id,))
            if not kopf:
                raise HTTPException(404, "Fall unbekannt")
            freigabe = alle(conn, "SELECT * FROM app.freigaben WHERE fall_id = %s", (fall_id,))
            entscheidungen = alle(
                conn,
                "SELECT * FROM app.entscheidungen WHERE fall_id = %s ORDER BY erstellt",
                (fall_id,),
            )
            # Spur des aktuellen Laufs: der vorgelegte Lauf oder die letzte Entscheidung
            lauf = (
                freigabe[0]["run_id"]
                if freigabe
                else (entscheidungen[-1]["run_id"] if entscheidungen else None)
            )
            spur = alle(
                conn,
                "SELECT ts, run_id, knoten, tool, args_geschwaerzt, policy_regel, ergebnis, "
                "modell, tokens_ein, tokens_aus FROM audit.ereignisse "
                "WHERE fall_id = %s AND run_id = %s ORDER BY ts, id",
                (fall_id, lauf),
            )
        return VORLAGEN.TemplateResponse(
            request,
            "fall.html",
            {
                "fall": kopf[0],
                "freigabe": freigabe[0] if freigabe else None,
                "entscheidungen": entscheidungen,
                "spur": spur,
                "lauf": lauf,
            },
        )

    @app.get("/fall/{fall_id}/pdf")
    def pdf(fall_id: str) -> FileResponse:
        with verbindung() as conn:
            zeile = conn.execute(
                "SELECT pdf_pfad FROM app.faelle WHERE fall_id = %s", (fall_id,)
            ).fetchone()
        if zeile is None:
            raise HTTPException(404, "Fall unbekannt")
        pfad = Path(str(zeile[0])).resolve()
        # Nur PDFs unterhalb des Datenordners ausliefern, egal was in der Datenbank steht.
        if pfad.suffix != ".pdf" or not pfad.is_relative_to(daten) or not pfad.exists():
            raise HTTPException(404, "PDF nicht verfügbar")
        return FileResponse(pfad, media_type="application/pdf")

    @app.post("/fall/{fall_id}/entscheidung", response_class=HTMLResponse)
    def entscheidung(
        request: Request,
        fall_id: str,
        aktion: Annotated[str, Form()],
        name: Annotated[str, Form()] = "",
    ) -> Response:
        if aktion not in ("freigeben", "zurueckhalten"):
            raise HTTPException(400, "Unbekannte Aktion")
        fehler: str | None = None
        ergebnis = None
        try:
            with verbindung() as conn:
                ergebnis = mensch.entscheide(conn, fall_id, aktion == "freigeben", name, fortsetzen)
        except mensch.FreigabeFehler as e:
            fehler = str(e)
        if "hx-request" not in request.headers:
            return RedirectResponse(f"/fall/{fall_id}", status_code=303)
        antwort = VORLAGEN.TemplateResponse(
            request,
            "_entscheidung.html",
            {"fall_id": fall_id, "ergebnis": ergebnis, "fehler": fehler, "name": name},
            status_code=409 if fehler else 200,
        )
        if ergebnis is not None:
            antwort.headers["HX-Refresh"] = "true"  # Status, Entscheidungen und Spur neu laden
        return antwort

    @app.get("/audit", response_class=HTMLResponse)
    def audit(request: Request, fall_id: str = "", run_id: str = "") -> Response:
        bedingungen: list[str] = []
        params: list[str] = []
        if fall_id:
            bedingungen.append("fall_id = %s")
            params.append(fall_id)
        if run_id:
            bedingungen.append("run_id = %s")
            params.append(run_id)
        wo = f"WHERE {' AND '.join(bedingungen)}" if bedingungen else ""
        with verbindung() as conn:
            zeilen = alle(
                conn,
                # Nur feste SQL-Teile; Filterwerte gehen als Parameter.
                f"SELECT * FROM audit.ereignisse {wo} ORDER BY id DESC LIMIT 300",
                tuple(params),
            )
        return VORLAGEN.TemplateResponse(
            request, "audit.html", {"zeilen": zeilen, "fall_id": fall_id, "run_id": run_id}
        )

    return app
