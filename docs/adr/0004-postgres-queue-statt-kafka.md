# 0004: Postgres-Queue statt Kafka

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Eingehende Rechnungen müssen von mehreren Workern parallel abgearbeitet werden, ohne dass ein Fall doppelt bearbeitet wird oder verloren geht, auch wenn ein Worker abstürzt. Die Entscheidung muss zusammen mit dem Statuswechsel gespeichert werden. Die Last liegt bei Hunderten bis wenigen Tausend Rechnungen am Tag, nicht bei Millionen Ereignissen pro Sekunde.

## Entscheidung

Die Queue ist die Tabelle `app.faelle` in derselben Postgres-Datenbank, in der auch ERP-Spiegel, Entscheidungen und Audit-Log liegen (`src/invoice_agent/queue.py`):

- **Holen:** `UPDATE … WHERE fall_id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING …`. Kein Worker wartet auf die Sperre eines anderen, keiner bekommt denselben Fall.
- **Erledigen:** Entscheidung einfügen und Status auf `erledigt` setzen, in **einer** Transaktion.
- **Fehler:** zurück auf `offen`, nach drei Versuchen `fehler`.
- **Absturz:** Fälle, die länger als eine Frist `in_arbeit` sind, öffnet der nächste Worker beim Start wieder.
- Der Worker läuft als Rolle `ia_agent` und liest die Welt für die Policy aus der Datenbank.

## Alternativen

- **Kafka (oder Confluent):** verworfen. Ein Broker mehr, Exactly-once zwischen Broker und Datenbank erfordert Outbox oder Transaktionen über zwei Systeme. Der Nutzen (Durchsatz, Replays über viele Konsumenten) wird bei dieser Last nicht gebraucht.
- **Redis/RQ, Celery:** ein zusätzlicher Dienst ohne Transaktion mit der Entscheidung.
- **LangGraph-Checkpointer als Queue:** Checkpoints speichern den Zustand eines Laufs, sie verteilen keine Arbeit.

## Konsequenzen

- Getestet gegen die echte Datenbank (`tests/test_queue.py`): SKIP LOCKED, sechs Threads ohne Doppelbearbeitung, Wiederholung und Markierung als `fehler`, hängende Fälle.
- Der Agent wartet bei einer Freigabe über der Grenze auf einen Menschen. Im Worker wird das als ESKALIEREN gespeichert. Ein Statuswert `wartet_auf_mensch` mit persistentem Checkpointer zum Fortsetzen fehlt noch.
- Falsch wäre die Entscheidung, wenn Ereignisse aus vielen Quellsystemen in Echtzeit kommen und mehrere Verbraucher sie unabhängig lesen müssen. Dann gehört ein Broker davor, und Postgres bleibt die Arbeitsliste.
