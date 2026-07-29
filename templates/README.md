# Vorlagen (Templates)

Hier gehört die leere Basis-STL des Airlocks hin:

    templates/DisposableLock_v2.stl

Diese Binärdatei ist **nicht im Git-Verlauf enthalten** (sie wurde über die
automatische Einrichtung nicht mitübertragen). Lege sie hier ab, bevor du den
Generator startest oder die Tests ausführst — sie liegt dem Auslieferungs-ZIP
(`airlock-stl-generator.zip`) bei bzw. ist deine Original-Konstruktionsdatei.

OpenSCAD liest sowohl binäre als auch ASCII-STL; beides funktioniert identisch.
Die gegen diese Vorlage validierten Präge-Parameter stehen in `app/config.py`
(`TemplateProfile`) und in `ARCHITECTURE.md` §2.
