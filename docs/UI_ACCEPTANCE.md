# UI ஏற்றுக்கொள்ளல் மற்றும் அணுகல்தன்மைச் சோதனைகள்

## நோக்கம்

T5.5 சோதனைகள் தமிழ் இடைமுகத்தின் முக்கிய வழித்தடங்கள் புரிந்துகொள்ளக்கூடியதாகவும்,
keyboard மற்றும் assistive-technology பயன்பாட்டுக்கு ஏற்ற semantic அடித்தளத்துடனும்,
தவறான உள்ளீடு அல்லது தரவு இல்லாதபோதும் 500 பிழையின்றியும் இருப்பதை உறுதிப்படுத்துகின்றன.

## தானியங்கி coverage

`tests/test_ui_acceptance.py` கீழுள்ள காட்சிகளை Flask test client மூலம் சோதிக்கிறது:

- `/`
- `/calendar?year=2026`
- `/prediction?year=2026&mode=aadi&view=day`
- `/prediction?year=2026&mode=aadi&view=week`
- `/prediction?year=2026&mode=aadi&view=month`
- `/observations`

ஒவ்வொரு பக்கத்திலும் UTF-8 response, `lang="ta"`, தமிழ் உள்ளடக்கம், page title,
ஒரே H1, ஒரே `main`, skip-link target, duplicate அல்லாத IDs, labelled form controls,
பெயரிடப்பட்ட buttons, table caption/header scope, SVG accessible name மற்றும் mobile
viewport metadata சரிபார்க்கப்படுகின்றன.

தவறான ஆண்டு/mode/view மற்றும் observation date filters தெளிவான தமிழ் fallback-க்கு
மாற்றப்படுவதும் சோதிக்கப்படுகிறது. தரவுத்தளம் migrate ஆகாதது, configured location இல்லாதது,
weather rows இல்லாதது மற்றும் forecast evidence இல்லாதது போன்ற no-data நிலைகள்
புரிந்துகொள்ளக்கூடிய செய்தியுடன் HTTP 200 வழங்க வேண்டும்.

## இடைமுகப் பாதுகாப்புகள்

- keyboard பயனருக்கான “முக்கிய உள்ளடக்கத்திற்குச் செல்ல” skip link
- தெளிவான `:focus-visible` indicator
- input, select, button மற்றும் navigation links-க்கு குறைந்தது 44px உயரம்
- explicit form labels மற்றும் current tab/date indication
- data tables-க்கு caption மற்றும் scoped column headers
- observation charts-க்கு accessible SVG title/name
- 760px-க்கு கீழ் calendar, forecast மற்றும் observation rows-க்கு card layout
- `prefers-reduced-motion` மற்றும் Windows/high-contrast `forced-colors` ஆதரவு
- செல்லாத query parameters-க்கு silent fallback அல்லாமல் visible Tamil status message

## இயக்குவது

```bash
source .venv/bin/activate
python -m pytest tests/test_ui_acceptance.py -q
```

முழுச் சோதனைத் தொகுப்பிற்கு:

```bash
python -m pytest -q
```

## வெளியீட்டுக்கு முன் manual check

இந்த structural automation முழுமையான WCAG certification அல்ல. Production release-க்கு முன்
Chrome/Firefox/Safari-ல் 320px mobile மற்றும் desktop widths, 200% zoom, keyboard-only
navigation, Tamil font rendering, VoiceOver/NVDA page landmarks மற்றும் data-table reading
order ஆகியவற்றை நேரடியாகச் சரிபார்க்க வேண்டும்.
