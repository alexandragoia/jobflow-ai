# Architektur und Entscheidungen

FastAPI stellt eine HTML/CSS/JavaScript-Oberfläche und Endpunkte mit Pydantic-Datenverträgen bereit. SQLAlchemy speichert Anzeigen, Quellen, Suchergebnisse und Rückmeldungen in SQLite. Konfiguration und Erkennungsmuster liegen in lesbaren YAML-Dateien.

## Ablauf einer Suche

1. Suchbegriffe, Radius, Alter der Anzeige und Arbeitszeit prüfen.
2. Anzeigen von Adzuna oder aus den Demo-Beispielen beziehen.
3. Datumswerte, Felder und Identitäten vereinheitlichen; unbekannte Angaben erhalten.
4. Eindeutige Dubletten zusammenführen und vorhandene Rückmeldungen übernehmen.
5. Bereits bewertete oder gespeicherte Anzeigen aus neuen Suchergebnissen auslassen.
6. Ausschlusskriterien nur auf ausdrückliche Angaben anwenden.
7. Merkmale lokal erkennen und Relevanz sowie nachvollziehbare Bewertung berechnen.
8. Eine Momentaufnahme speichern; beim Abrufen von Verlauf oder Sammlung die aktuelle Rückmeldung ergänzen.

## Optionale KI

Die Person wählt Anzeigen aus und erhält eine Vorschau mit neuen Anfragen, vorhandenen Analysen und verbleibendem Kontingent. Die Responses-API liefert strukturierte Daten und Textbelege nach einem strikten Schema. Zitate werden gegen Titel und Anzeigenauszug geprüft. Der Cache berücksichtigt Inhalt, Prompt-/Schemaversion und Modell. Bei ungültigen Antworten oder Dienstfehlern bleibt die lokale Auswertung verfügbar.

Anzeigentexte sind nicht vertrauenswürdige Inhalte. Die KI verändert keine Filter, führt keinen Code aus und lädt keine Originalseiten herunter. Ein vorhandenes Zitat allein bestätigt noch nicht die Richtigkeit einer Interpretation.

## Präferenzen

Rückmeldungen und konkrete Gründe erzeugen lokale Zusammenhänge. Erst bei ausreichenden Signalen werden kleine Änderungen der Gewichtung vorgeschlagen. Annahme, Ablehnung und Rücknahme werden gespeichert. Speichern allein bedeutet kein Interesse. Eine bedingte Interessenbekundung gilt nicht als Zustimmung zu allen Bedingungen einer Anzeige.

## Speicherung und Sicherheit

SQLite und additive Migrationen erhalten bestehende Daten. Der Browser merkt sich Filter, aber keine API-Schlüssel. Links werden geprüft; die Oberfläche verwendet textContent, eine Content Security Policy, erlaubte Hosts und eine Herkunftsprüfung bei Schreibzugriffen. Für den vorbereiteten Online-Betrieb gibt es PBKDF2-Passwortableitung, signierte Cookies, begrenzte Anmeldeversuche und einen dauerhaften Datenordner. Vor Online-Nutzung muss der konkrete Betrieb überprüft werden.

## Umfang

Ein Prozess und eine lokale Datenbank halten den Betrieb einer persönlichen Anwendung überschaubar. Externe APIs verwenden Zeitlimits, Cache und lokale Kontingente. Weitere Portale sind als Suchlinks gekennzeichnet. Die Demo ersetzt die Beschaffung der Anzeigen und verwendet danach die normale Verarbeitung für Normalisierung, Filter, Bewertungen und Speicherung.
