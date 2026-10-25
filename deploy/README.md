# Betrieb in Azure Container Apps (Runbook für den Eigentümer)

Dieses Verzeichnis enthält alles, um den Prüfdienst als Azure Container App zu betreiben. Die Schritte mit **[Eigentümer]**
macht nur du selbst (Konto, Zahlungsdaten, Anmeldung); das Repository enthält keine Zugangsdaten.

Ergebnis: ein öffentlicher HTTPS-Endpunkt (`https://<fqdn>`), `/health` offen, `/validate` nur mit Header `X-Api-Key`.
Der Dienst skaliert auf null Replikate (min 0, max 1) und startet bei der ersten Anfrage (Kaltstart, rund eine bis zwei Minuten).

## Einmalige Einrichtung

1. **[Eigentümer]** Kostenloses Azure-Konto anlegen (https://azure.microsoft.com/free). Die Karte dient nur der Identitätsprüfung;
   es gibt 200 USD Guthaben für 30 Tage. Danach auf Pay-as-you-go umstellen (Upgrade im Portal), damit die dauerhaft
   kostenlosen Kontingente weiter gelten. Sofort danach unter Cost Management > Budgets ein Budget von **1 EUR** pro Monat
   mit E-Mail-Warnung anlegen.
2. **[Eigentümer]** Azure CLI installieren: `winget install Microsoft.AzureCLI`, neues Terminal öffnen, `az login`.
3. Image veröffentlichen: Tag auf `main` setzen und pushen (zum Beispiel `git tag v0.2.0-rc1 && git push origin v0.2.0-rc1`).
   Der Workflow `release` baut das Image und legt es unter `ghcr.io/harispaartan/e-rechnung-eingang:<tag>` ab.
   Sein Job `deploy` scheitert vorerst beim Azure-Login, weil Schritt 7 noch fehlt; das ist erwartet.
4. **[Eigentümer]** Das GHCR-Paket einmal öffentlich schalten (sonst kann Azure das Image nicht ohne Zugangsdaten ziehen):
   GitHub > dein Profil > Packages > `e-rechnung-eingang` > Package settings > Change visibility > Public.
5. Erstbereitstellung aus dem Repository-Wurzelverzeichnis (Git Bash):
   `deploy/azure.sh v0.2.0-rc1`
   Das Skript erzeugt beim ersten Lauf den API-Schlüssel in `deploy/.secrets/ere_api_key` (git-ignoriert; nie teilen, nie in
   Chats oder Tickets einfügen), legt `rg-erechnung` in `germanywestcentral` an und stellt `containerapp.bicep` bereit.
   Am Ende gibt es die URL aus. Erneutes Ausführen mit einem anderen Tag ist die Aktualisierung.
6. Test (der erste Aufruf braucht wegen des Kaltstarts bis zu zwei Minuten):
   `curl -s https://<fqdn>/health` muss `"status":"ok"` liefern. Vollständiger Test mit Messwerten:
   `uv run python tools/smoke_remote.py --base-url https://<fqdn>`
   (liest den Schlüssel aus `deploy/.secrets/ere_api_key`; prüft Health, 401 ohne Schlüssel, gültige XRechnung und gültiges
   ZUGFeRD-PDF, 413 über 10 MB).
   *Erst live prüfbar:* Der 413-Fall sendet 11 MiB; manche Ingress-Stacks trennen die Verbindung, während noch geschrieben
   wird. Dann steht `"too_large": "reset"` in der Ausgabe statt 413. Das wird beim ersten echten Lauf geprüft, bevor ein
   Release-Tag gesetzt wird.
7. Automatische Bereitstellung per GitHub Actions (ohne gespeicherte Azure-Passwörter, nur OIDC):
   1. `deploy/github-oidc.sh` ausführen (nach Schritt 5, die Ressourcengruppe muss existieren). Es legt die Entra-App
      `erechnung-github-deploy` mit Federated Credential für die GitHub-Umgebung `production` an, gibt ihr Contributor nur auf
      `rg-erechnung` und gibt drei Kennungen aus.
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

## Kosten

Die Container App läuft im Verbrauchsplan mit 1 vCPU und 2 GiB und kostet nichts, solange sie unter den monatlichen
Gratiskontingenten bleibt: 180.000 vCPU-Sekunden, 360.000 GiB-Sekunden und 2 Millionen Anfragen.

Rechenbeispiel Demo: 500 Prüfungen im Monat zu je rund 3 Sekunden sind 1.500 vCPU-s und 3.000 GiB-s. Dazu 30 Kaltstarts zu
je rund 120 Sekunden (Start wird mit abgerechnet) sind 3.600 vCPU-s und 7.200 GiB-s. Zusammen etwa 5.100 vCPU-s und
10.200 GiB-s, also unter 3 Prozent der Kontingente; 500 Anfragen sind 0,025 Prozent der 2 Millionen. Auch das Zehnfache bleibt
im Gratisbereich. Log Analytics (`law-erechnung`) enthält im Tarif PerGB2018 monatlich 5 GB kostenlose Aufnahme, ein
Demo-Dienst bleibt weit darunter. GHCR ist für öffentliche Pakete kostenlos. Bei Zweifel gilt das Budget aus Schritt 1 als
Frühwarnung.
