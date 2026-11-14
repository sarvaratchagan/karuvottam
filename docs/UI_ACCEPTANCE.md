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
- `/events?year=2025`
- `/climate`

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

## Stitch வடிவமைப்பு QA (D5)

Google Stitch mockup ஒரு காட்சி வழிகாட்டியாக மட்டும் பயன்படுத்தப்படுகிறது. முகப்பு மற்றும்
துணைப் பக்கங்கள் காட்டும் இடம், சாளரம், வானிலைப் பதிவு, forecast நிலை, provenance மற்றும்
எச்சரிக்கைகள் அனைத்தும் ஏற்கனவே உள்ள read models அல்லது தெளிவான no-data நிலையில் இருந்து
வர வேண்டும்; mockup-இல் உள்ள எடுத்துக்காட்டு telemetry மதிப்புகள் நகலெடுக்கப்படக் கூடாது.

தானியங்கி D5 regression checks கீழுள்ளவற்றையும் உறுதிப்படுத்துகின்றன:

- ஒவ்வொரு பொதுப் பக்கத்திலும் பகிரப்பட்ட research shell மற்றும் சரியான active navigation
- research navigation-ல் ஒரே ஒரு `aria-current="page"`
- Google Fonts, Tailwind CDN போன்ற வெளிப்புற runtime design dependency இல்லாமை
- 760px மற்றும் 480px responsive guards, horizontal navigation scrolling
- protected workspace/admin shell-க்கு authenticated regression coverage

Manual browser QA matrix:

| அகலம் | சரிபார்க்கப்பட்ட காட்சிகள் | ஏற்றுக்கொள்ளல் |
|---|---|---|
| Desktop (1792px) | முகப்பு, காலண்டர், observations, events | shell, cards, filters மற்றும் data surfaces overflow இல்லாமல் வாசிக்கக்கூடியவை |
| Mobile (390px) | முகப்பு, observations | navigation scrollable; cards stack; document horizontal overflow இல்லை |
| Narrow mobile (320px) | forecast, events | filters wrap/stack; tables அல்லது event surfaces viewport-ஐ விரிவாக்கக்கூடாது |

Browser QA-வில் `document.documentElement.scrollWidth` viewport அகலத்தை மீறாததும்,
ஒவ்வொரு வழித்தடத்திலும் எதிர்பார்த்த H1 மற்றும் active navigation label இருப்பதும்
சரிபார்க்கப்பட வேண்டும்.

## தமிழ் / ஆங்கில மொழித் தேர்வு (T9.7)

பக்கத்தின் கீழ் வலப்புறத்தில் தமிழ் / English தேர்வு உள்ளது. `?lang=en` அல்லது
`?lang=ta` மூலம் தேர்வு செய்யலாம்; தேர்வு cookie-யில் நினைவில் வைக்கப்பட்டு அடுத்த
பக்கங்களிலும் தொடரும். பக்கத் தலைப்புகள், வழிசெலுத்தல், தரவு அட்டவணை உரைகள்,
விளக்கங்கள், எச்சரிக்கைகள், accessibility labels மற்றும் PWA manifest மொழிக்கு
ஏற்ப மாறும். இணையமில்லாத பக்கம் கடைசியாகத் தேர்ந்தெடுத்த மொழியைப் பயன்படுத்தும்.

`tests/test_localization.py` பொதுப் பக்கங்கள், தேர்வு நினைவில் நிற்றல், query filters,
தமிழ் இயல்புநிலை, ஆங்கில date/unit labels, PWA மற்றும் பிழைப் பக்கத்தைக்
சோதிக்கிறது. புதிய UI உரைகள் சேர்க்கும்போது
`karuvottam/locales/en.json` அல்லது `karuvottam/localization.py`-இல் மொழிபெயர்ப்பையும்
சேர்த்து இரு மொழிகளிலும் பக்கத்தைச் சரிபார்க்க வேண்டும். இடப்பெயர்கள் மற்றும்
"கருவோட்டம்" போன்ற திட்டப் பெயர் மொழிபெயர்க்கப்படாமல் ஒலிபெயர்க்கப்படலாம்.

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
