# Vorlagen (Templates)

Hier liegt die leere Basis-STL des Airlocks:

    templates/DisposableLock_v2.stl

Sie ist im Repository enthalten — Generator und Tests laufen damit out-of-the-box.
Du kannst sie durch deine eigene Konstruktionsdatei ersetzen; OpenSCAD liest sowohl
binäre als auch ASCII-STL. Die gegen diese Vorlage validierten Präge-Parameter stehen
in `app/config.py` (`TemplateProfile`) und in `ARCHITECTURE.md` §2.

Weitere Lock-Modelle lassen sich später als zusätzliche `TemplateProfile`-Einträge
mit eigenen Vorlagen und Präge-Parametern ergänzen.
