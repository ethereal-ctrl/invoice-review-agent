#!/bin/zsh
# Einmaliger Test-Lauf aller Stufen (Plan: Nacht Sa -> So). Aufruf: scripts/testlauf.sh [split]
#
# - Stufen ohne LLM werden direkt ausgewertet.
# - LLM-Stufen: erst Cache vorwärmen (wiederholt nur Netz- und Anbieterfehler, speichert keine
#   Entscheidungen), dann genau ein gespeicherter Lauf im Replay-Modus. Fehlt dabei ein
#   Cache-Eintrag, bricht der Lauf vor dem Speichern ab; das Test-Register bleibt frei.
# - Nur API (NVIDIA NIM), keine lokalen Modelle. Mac nicht zuklappen.
set -u
cd "${0:A:h}/.." || exit 1
SPLIT=${1:-test}
WORKER=${WORKER:-6}
mkdir -p runs
LOG=runs/TESTLAUF_${SPLIT}_$(date +%Y%m%dT%H%M%S).log
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "Start: Split $SPLIT, $WORKER Worker"
for stufe in b0 b1 regeln; do
  if uv run invoice eval --stufe "$stufe" --split "$SPLIT" >> "$LOG" 2>&1; then
    log "$stufe gespeichert"
  else
    log "$stufe FEHLER oder bereits ausgewertet (siehe Log)"
  fi
done

for stufe in llm:nim_gross agent:nim_gross; do
  log "$stufe: Cache vorwärmen"
  if uv run invoice vorwaermen --stufe "$stufe" --split "$SPLIT" --versuche 4 --pause 300 \
       --worker "$WORKER" >> "$LOG" 2>&1; then
    if uv run invoice eval --stufe "$stufe" --split "$SPLIT" --replay >> "$LOG" 2>&1; then
      log "$stufe gespeichert"
    else
      log "$stufe: Replay-Lauf FEHLGESCHLAGEN, nichts gespeichert (siehe Log)"
    fi
  else
    log "$stufe: nicht alle Fälle beantwortet, Test-Lauf NICHT gespeichert. Später erneut starten."
  fi
done
log "Ende"
