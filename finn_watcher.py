name: FINN Angebots-Watcher

on:
  schedule:
    # Stuendlich zur vollen Stunde (UTC)
    - cron: "0 * * * *"
  workflow_dispatch: {}   # erlaubt manuelles Starten ueber die GitHub-Oberflaeche

permissions:
  contents: write   # noetig, damit der Workflow state.json zurueck committen kann

concurrency:
  group: finn-watch
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Repository auschecken
        uses: actions/checkout@v4

      - name: Python einrichten
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Abhaengigkeiten installieren
        run: |
          pip install -r requirements.txt
          playwright install --with-deps chromium

      - name: Watcher ausfuehren
        env:
          FINN_URL: ${{ vars.FINN_URL }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python finn_watcher.py

      - name: Aktualisierten Stand committen
        run: |
          git config user.name "finn-watcher-bot"
          git config user.email "actions@github.com"
          git add state.json
          if ! git diff --cached --quiet; then
            git commit -m "Update state.json [skip ci]"
            git push
          else
            echo "Keine Aenderung am Stand."
          fi
