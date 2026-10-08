# Datenmodell

SQLite speichert die Daten in `jobflow.db`. Interne Datumswerte werden als UTC ohne Zeitzoneninformation in den Spalten gespeichert. Die API gibt Veröffentlichungsdaten im ISO-Tagesformat aus. Veröffentlichung, Abruf und Aktualisierung sind getrennte Angaben.

| Tabelle | Inhalt |
|---|---|
| `sources` | Quellenkatalog, Zugriffsart, Status, letzter Abruf und Fehler |
| `searches` | Begriffe, Radius, Alter, vollständige Parameter, Meldungen und geschätzte Gesamtzahl |
| `source_runs` | Quelle und Suche, Zeitpunkt, Ergebnis, Anzahl und Dauer |
| `api_usage` | Adzuna-Anfragen einschließlich Fehlern; Endpunkt ohne Schlüssel |
| `jobs` | Logische Anzeige, vereinheitlichte Inhalte, Koordinaten und Qualität, Datum, Arbeitszeit, erste/letzte Sichtung und mögliche Wiederveröffentlichung |
| `job_sources` | Identität innerhalb der Quelle, Original-URL, gegebenenfalls Bewerbungs-URL und Abrufdatum |
| `job_aliases` | Zusammengeführte Identitäten für die Nutzung älterer Suchergebnisse |
| `search_results` | Zuordnung von Suche und Anzeige, Status, Ausschlussgrund, Zitate, Bewertung und JSON-Momentaufnahme |
| `job_feedback` | Aktuelle Rückmeldung, unabhängiger Favorit, optionaler Grund und Notiz |
| `analysis_cache` | Validiertes JSON nach Inhaltshash, Prompt-Version und Modell |
| `search_cache` | Suchantwort nach Hash der öffentlichen Parameter; 15 Minuten gültig |
| `llm_usage` | OpenAI-Anfragen für das lokale 24-Stunden-Kontingent |
| `learning_decisions` | Vorschläge zur Gewichtung, Entscheidung, Textbelege und Rücknahme |

## Identität und Erhaltung

`job_sources(source_id, source_job_id)` und `search_results(search_id, job_id)` sind eindeutig. Eine bekannte Quellenidentität aktualisiert die vorhandene Anzeige. Übereinstimmende kanonische URLs werden derselben Anzeige zugeordnet. Bei der URL-Normalisierung werden bekannte `utm_*`-Parameter und Fragmente entfernt; identifizierende Parameter bleiben erhalten.

Übereinstimmungen von Titel, Unternehmen und Ort mit sehr ähnlichem Text und gleichem Datum können zusammengeführt werden. Links und Rückmeldungen bleiben erhalten. Bei einem anderen Datum wird eine mögliche Wiederveröffentlichung gekennzeichnet. Unternehmensnamen werden nur vorsichtig normalisiert.

Ein Ausschluss gehört zur jeweiligen Suche. Neue Filter ändern frühere Ergebnisse nicht stillschweigend. Die gespeicherte Momentaufnahme erhält die damalige Erklärung; die aktuelle Rückmeldung wird unabhängig davon über die Anzeigenidentität abgerufen.

Bei Dubletten werden vorhandene Favoriten und die jüngste gültige Rückmeldung übernommen. Frühere Identitäten bleiben als Alias erhalten. Favoriten sind unabhängig von Interesse oder Ablehnung: Das Entfernen einer Rückmeldung löscht keinen Favoriten.

## Migrationen und Datenschutz

`migrations.py` ergänzt fehlende Spalten und wandelt ältere `liked`-Angaben in Interesse oder Ablehnung um. Migrationen sind idempotent und löschen keine Tabellen oder Datensätze. Vor der ersten Aktualisierung entsteht `jobflow.db.bak`.

`config/qualifications.yaml` ist optional, lokal und von Git ausgeschlossen. Die öffentliche Vorlage heißt `qualifications.example.yaml`. Auch `.env`, SQLite-Dateien und temporäre Daten sind ausgeschlossen. Tabellen speichern keine Adzuna- oder OpenAI-Schlüssel. Das Qualifikationsprofil wird nicht an den KI-Dienst gesendet.

Ältere Suchverläufe können ohne zugeordnete Ergebnisse vorliegen. Fehlende historische Zuordnungen werden nicht erfunden.

## Entscheidungen zur Gewichtung

`learning_decisions` enthält Vorschlagsidentität, Kriterium, Richtung, bisheriges und vorgeschlagenes Gewicht, Status (`accepted`, `dismissed`, `undone`), Anzeigen-IDs als Belege und Erstellungsdatum. Die zusätzliche Tabelle verändert keine vorhandenen Rückmeldungen. Bereits angenommene oder rückgängig gemachte Signale gelten als verarbeitet, damit dieselbe Anpassung nicht wiederholt angewendet wird.

`job_feedback.interest_note` hält Erklärungen für Interesse oder Speichern getrennt von der Ablehnungsnotiz `note`. `interest_conditional` kennzeichnet Interesse an einer bestimmten Variante oder Bedingung. Beide Felder werden ohne Änderung älterer Notizen ergänzt und bei Dubletten erhalten.
