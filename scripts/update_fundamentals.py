name: কোম্পানির ক্যাটাগরি ও EPS আপডেট

on:
  schedule:
    # প্রতি শনিবার ঢাকা সময় সকাল ৯টা (UTC ০৩:০০)। ত্রৈমাসিক ফল সপ্তাহের মাঝে আসে, তাই সাপ্তাহিক যথেষ্ট।
    - cron: '0 3 * * 6'
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: dse-data
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: ক্যাটাগরি ও EPS নামান
        run: python scripts/update_fundamentals.py

      - name: পরিবর্তন সেভ করুন
        if: ${{ always() }}
        run: |
          git config user.name "dse-data-bot"
          git config user.email "dse-data-bot@users.noreply.github.com"
          git add docs/data
          if git diff --cached --quiet; then
            echo "নতুন কিছু নেই"
          else
            git commit -m "fundamentals: $(date -u +%F)"
            git pull --rebase
            git push
          fi
