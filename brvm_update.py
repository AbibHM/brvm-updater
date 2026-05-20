name: BRVM Daily Update

on:
  # 16h30 GMT = fin séance BRVM (Abidjan = UTC+0, séance 09h-15h30)
  # brvm.org publie les cours ~30-60 min après la clôture
  schedule:
    - cron: "30 16 * * 1-5"

  # Déclenchement manuel avec option de forcer une date passée
  workflow_dispatch:
    inputs:
      date_override:
        description: "Date à forcer (YYYY-MM-DD) — laisser vide pour aujourd'hui"
        required: false
        default: ""

jobs:
  update:
    name: Scrape BRVM → Supabase
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run BRVM updater
        env:
          SUPABASE_URL:  ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY:  ${{ secrets.SUPABASE_KEY }}   # ← doit être service_role dans les secrets
          DATE_OVERRIDE: ${{ github.event.inputs.date_override }}
        run: python brvm_update.py

      - name: Notify on failure
        if: failure()
        run: |
          echo "❌ BRVM update failed on $(date -u)"
          echo "Vérifier les logs ci-dessus."
          echo "Si brvm.org est indisponible, relancer manuellement demain."
