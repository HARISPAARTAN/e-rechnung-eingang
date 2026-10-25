# Betrieb in Azure Container Apps (Runbook für den Eigentümer)

Dieses Verzeichnis enthält alles, um den Prüfdienst als Azure Container App zu betreiben. Die Schritte mit **[Eigentümer]**
macht nur du selbst (Konto, Zahlungsdaten, Anmeldung); das Repository enthält keine Zugangsdaten.

Ergebnis: ein öffentlicher HTTPS-Endpunkt (`https://<fqdn>`), `/health` offen, `/validate` nur mit Header `X-Api-Key`.
Der Dienst skaliert auf null Replikate (min 0, max 1) und startet bei der ersten Anfrage (Kaltstart, gemessen rund 20 Sekunden, siehe Messwerte unten).

## Einmalige Einrichtung

1. **[Eigentümer]** Kostenloses Azure-Konto anlegen (https://azure.microsoft.com/free). Die Karte dient nur der Identitätsprüfung;
   es gibt 200 USD Guthaben für 30 Tage. Danach auf Pay-as-you-go umstellen (Upgrade im Portal), damit die dauerhaft
   kostenlosen Kontingente weiter gelten. Sofort danach unter Cost Management > Budgets ein Budget von **1 EUR** pro Monat
   mit E-Mail-Warnung anlegen.
2. **[Eigentümer]** Azure CLI installieren: `winget install Microsoft.AzureCLI`, neues Terminal öffnen, `az login`.
3. Image veröffentlichen: Tag auf `main` setzen und pushen (zum Beispiel `git tag v0.2.0-rc1 && git push origin v0.2.0-rc1`).
   Der Workflow `release` baut das Image und legt es unter `ghcr.io/harispaartan/e-rechnung-eingang:<tag>` ab. Beim Hochladen
   einer Ebene kann GHCR gelegentlich vorübergehend `unknown blob` melden (so bei `v0.2.0-rc2`); dann den Lauf in Actions
   mit "Re-run failed jobs" wiederholen, es genügt ein zweiter Versuch.
   Sein Job `deploy` scheitert vorerst beim Azure-Login, weil Schritt 7 noch fehlt; das ist erwartet.
4. **[Eigentümer]** Das GHCR-Paket einmal öffentlich schalten (sonst kann Azure das Image nicht ohne Zugangsdaten ziehen):
   GitHub > dein Profil > Packages > `e-rechnung-eingang` > Package settings > Change visibility > Public.
5. Erstbereitstellung aus dem Repository-Wurzelverzeichnis (Git Bash):
   `deploy/azure.sh v0.2.0-rc1`
   Das Skript erzeugt beim ersten Lauf den API-Schlüssel in `deploy/.secrets/ere_api_key` (git-ignoriert; nie teilen, nie in
   Chats oder Tickets einfügen), legt `rg-erechnung` in `germanywestcentral` an und stellt `containerapp.bicep` bereit.
   Am Ende gibt es die URL aus. Erneutes Ausführen mit einem anderen Tag ist die Aktualisierung.
6. Test (der erste Aufruf braucht wegen des Kaltstarts rund 20 Sekunden):
   `curl -s https://<fqdn>/health` muss `"status":"ok"` liefern. Vollständiger Test mit Messwerten:
   `uv run python tools/smoke_remote.py --base-url https://<fqdn>`
   (liest den Schlüssel aus `deploy/.secrets/ere_api_key`; prüft Health, 401 ohne Schlüssel, gültige XRechnung und gültiges
   ZUGFeRD-PDF, 413 über 10 MB).
   Der 413-Fall sendet 11 MiB. Gemessen gegen den echten Dienst: der Dienst antwortet immer 413 (im Container-Log
   `POST /validate 413 Content Too Large`), und der Ingress trennt danach die Verbindung, während der Client noch schreibt.
   `curl` zeigt dabei bei 10,1, 10,5 und 11 MiB, mit und ohne `Expect: 100-continue`, jedes Mal 413. Der Smoke-Test
   mit `httpx` auf Windows bekommt dagegen jedes Mal einen Transportfehler (`"too_large": "reset"`), weil er den ganzen
   Körper schreibt, bevor er liest, und der Verbindungsabbruch die Antwort verwirft; auf dem Linux-Runner von GitHub
   (Deploy-Job von `v0.2.0-rc2`) kam 413 an. Die Regel in `tools/smoke_remote.py` erwartet daher 413 und lässt
   `reset` nur gelten, wenn der Körper über der Grenze lag (der Test sendet immer 11 MiB) und `/health` danach noch 200
   liefert (Feld `health_after`); ein Dienst, der die Datei angenommen hätte, würde 200 oder 422 melden, nie einen Abbruch.
7. Automatische Bereitstellung per GitHub Actions (ohne gespeicherte Azure-Passwörter, nur OIDC):
   1. `deploy/github-oidc.sh` ausführen (nach Schritt 5, die Ressourcengruppe muss existieren; braucht `gh` mit Anmeldung). Es
      legt die Entra-App `erechnung-github-deploy` an, gibt ihr Contributor nur auf `rg-erechnung` und gibt drei Kennungen
      aus. Es legt **zwei** Federated Credentials für die GitHub-Umgebung `production` an, weil Entra den Subject-Wert
      exakt vergleicht und GitHub ihn in zwei Formen ausstellt:
      - `github-production`: `repo:HARISPAARTAN/e-rechnung-eingang:environment:production` (Namen)
      - `github-production-ids`: `repo:HARISPAARTAN@<Owner-ID>/e-rechnung-eingang@<Repo-ID>:environment:production`
        (numerische IDs, das Skript liest sie mit `gh api repos/HARISPAARTAN/e-rechnung-eingang --jq '.owner.id, .id'`).
      Beim ersten echten Deploy (Tag `v0.2.0-rc2`) zeigte GitHub die ID-Form; ohne dieses Credential scheitert der Login
      mit `AADSTS700213: No matching federated identity record found for presented assertion subject ...`. Die Fehlermeldung
      nennt den erwarteten Subject-Wert; ein neu gelegtes Repository oder ein Umbenennen/Übertragen ändert die IDs
      bzw. Namen, dann das Skript erneut ausführen (es legt nur Fehlendes an).
   2. **[Eigentümer]** GitHub > Repository > Settings > Environments > New environment `production`. Darin drei Secrets
      eintragen: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (Werte aus der Skriptausgabe) und das Secret
      `ERE_API_KEY` (Inhalt der Datei `deploy/.secrets/ere_api_key`, am besten ohne Umweg über die Zwischenablage-Historie).
   3. **[Eigentümer]** Settings > Secrets and variables > Actions > Variables: `ERE_BASE_URL` = `https://<fqdn>`
      (für den Keep-alive-Workflow).
   Ab dann aktualisiert jeder Tag `v*` das Image, die Container App und führt den Smoke-Test gegen die laufende URL aus.

## Betrieb

- **Leerlauf nach 90 Tagen:** Azure löscht Container-Apps-Umgebungen, die lange unbenutzt sind. Der Workflow `keepalive`
  ruft am 1. jedes Monats `/health` auf und schreibt die Kaltstartzeit ins Log; er läuft auch manuell (Actions >
  keepalive > Run workflow). `ERE_BASE_URL` darf mit oder ohne abschließenden Schrägstrich gespeichert werden. GitHub
  deaktiviert geplante Workflows nach 60 Tagen ohne Repository-Aktivität; dann genügt ein Commit oder ein manueller Lauf,
  um sie wieder zu aktivieren. Ist die Umgebung trotzdem weg: `deploy/azure.sh <tag>` stellt alles neu bereit (der Schlüssel
  bleibt gleich, die URL ändert sich eventuell; dann `ERE_BASE_URL` aktualisieren).
- **Schlüssel rotieren:** `deploy/.secrets/ere_api_key` löschen, `deploy/azure.sh <aktueller-tag>` erneut ausführen (erzeugt
  einen neuen Schlüssel und ersetzt das Container-App-Secret `api-key`), danach das GitHub-Secret `ERE_API_KEY` in der
  Umgebung `production` aktualisieren und (ab Meilenstein 3) die Dataverse-Umgebungsvariable mit dem neuen Schlüssel.
  **Wichtig:** Ein geändertes Secret startet eine laufende Revision nicht neu. Bis zum Neustart akzeptiert der Dienst noch
  den alten Schlüssel. Deshalb direkt nach dem Skript die aktive Revision neu starten:
  `REV=$(az containerapp revision list --name ca-erechnung --resource-group rg-erechnung --query "[?properties.active].name | [0]" -o tsv)`
  und `az containerapp revision restart --name ca-erechnung --resource-group rg-erechnung --revision "$REV"`.
  Danach mit `uv run python tools/smoke_remote.py --base-url https://<fqdn>` prüfen, dass der neue Schlüssel gilt.
- **Logs:** Portal > `ca-erechnung` > Log stream, oder Log Analytics `law-erechnung` (30 Tage Aufbewahrung).
- **Abbauen:** `az group delete --name rg-erechnung` entfernt alles.

## Messwerte (Erstbereitstellung, 2026-10-25)

Region `germanywestcentral`, 1 vCPU und 2 GiB, Revision `ca-erechnung--hbq4h1u` (Image `v0.2.0-rc1`, danach
`ca-erechnung--0000001` mit `v0.2.0-rc2`). Zeiten vom Rechner des Eigentümers (Windows, Heimnetz).

| Messung | Ergebnis |
|---|---|
| warmer `/health` | 0,1 s |
| warmes `/validate` (curl, mit TLS) | UBL 0,26 bis 0,31 s, ZUGFeRD-PDF 0,12 bis 0,16 s |
| Kaltstart nach Skalierung auf null (Smoke-Test, `seconds_until_ok`) | 22,6 s (16:51 Ortszeit; der Test fragt alle 5 s, also 17,6 bis 22,6 s) |
| Bestandteile des Kaltstarts laut System- und Konsolenlog (UTC) | Replik zugewiesen 15:51:41; Image gezogen in 5,0 s (142,6 MB); Container gestartet 15:51:49; uvicorn 15:51:58; erster Probe-Aufruf `/health` 200 um 15:51:59 |
| Abschaltung | Ereignis `KEDAScaleTargetDeactivated` (1 auf 0) um 15:50:31 UTC, `cooldownPeriod` 300 s |

Probe-Nachweis: Der erste Probe-Aufruf von `127.0.0.1` kommt 10 s nach `ContainerStarted` (`initialDelaySeconds: 10`) und
liefert 200; danach folgen `GET /health` im Takt der Readiness- (10 s) und Liveness-Probe (30 s), alle 200. Im Systemlog
steht kein `ProbeFailed`, die Revision hat `HealthState: Healthy`. Abruf:
`az containerapp logs show --name ca-erechnung --resource-group rg-erechnung --type system --tail 50` (nur Ereignisse seit
dem Abruf, zuverlässig während eines Kaltstarts) und `--type console` für die Aufrufe von `/health`.

Zum Image-Pull: Das öffentliche GHCR-Paket wurde ohne hinterlegte Zugangsdaten gezogen; der Fallback mit
`az containerapp registry set` war nicht nötig.

## Kosten

Die Container App läuft im Verbrauchsplan mit 1 vCPU und 2 GiB und kostet nichts, solange sie unter den monatlichen
Gratiskontingenten bleibt: 180.000 vCPU-Sekunden, 360.000 GiB-Sekunden und 2 Millionen Anfragen.

Rechenbeispiel Demo mit den gemessenen Werten (Obergrenze, weil die Abrechnung im Leerlauf günstiger sein kann): Eine
Sitzung besteht aus einem Kaltstart (rund 20 s) und den Anfragen; danach läuft die Replik noch 300 s (`cooldownPeriod`)
bis zur Abschaltung. Eine Sitzung zählt also rund 330 Replik-Sekunden, das sind 330 vCPU-s und 660 GiB-s. 30 Sitzungen
im Monat mit zusammen 500 Prüfungen (je rund 0,3 s) ergeben etwa 9.900 vCPU-s und 19.800 GiB-s, jeweils rund 5,5 Prozent der
Kontingente; 500 Anfragen sind 0,025 Prozent der 2 Millionen. Bis zur Grenze der Gratiskontingente wären es rund 545 Sitzungen
im Monat (180.000 s geteilt durch 330 s, etwa 18 pro Tag). Eine dauerhaft laufende Replik käme auf 2.592.000 Sekunden im Monat,
das 14-Fache des Kontingents; Skalierung auf null ist also Voraussetzung. Log Analytics (`law-erechnung`) enthält im Tarif PerGB2018 monatlich 5 GB kostenlose Aufnahme, ein
Demo-Dienst bleibt weit darunter. GHCR ist für öffentliche Pakete kostenlos. Bei Zweifel gilt das Budget aus Schritt 1 als
Frühwarnung.
