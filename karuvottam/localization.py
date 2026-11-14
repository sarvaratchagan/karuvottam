"""Small, dependency-free UI locale catalog and response helpers.

Tamil remains the source language.  Entries are ordered longest first when
applied so a specific message is not broken by a shorter label translation.
"""

from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from flask import request

LANGUAGES = ('ta', 'en')

ENGLISH = {
    'க': 'க',
    'அனுமதி இல்லை': 'Access denied',
    'இடம் செல்லாது; இயல்புநிலை இடம் காட்டப்படுகிறது.': 'Invalid location; showing the default location.',
    'இடைமதிப்பீடு': 'Interpolated',
    'இந்தக் குறிப்பு எண்ணுடன் நிர்வாகியைத் தொடர்புகொள்ளவும்.': 'Contact the administrator with this reference ID.',
    'இந்தச் செயல் அனுமதிக்கப்படவில்லை': 'This action is not permitted',
    'இந்தப் பக்கத்தைப் பார்க்க உங்கள் பங்கிற்கு அனுமதி இல்லை.': 'Your role does not permit access to this page.',
    'எச்சரிக்கை': 'Warning',
    'எதிர்பாராத பிழை ஏற்பட்டது': 'An unexpected error occurred',
    'கணக்கு அல்லது நிர்வாகச் சான்றுகளை அமைக்கவும்.': 'Configure an account or administrator credentials.',
    'கருவோட்ட வகை செல்லாது; ஆடி தேர்ந்தெடுக்கப்பட்டது.': 'Invalid Karuvottam type; Aadi was selected.',
    'காட்சி வகை செல்லாது; நாள் காட்சி காட்டப்படுகிறது.': 'Invalid view; showing the day view.',
    'கால வரம்பிற்கு வெளியே': 'Outside the time range',
    'காலநிலைச் சுட்டித் தரவுத்தளம் தற்போது கிடைக்கவில்லை.': 'The climate-index database is currently unavailable.',
    'கோரிக்கையை நிறைவேற்ற முடியவில்லை': 'The request could not be completed',
    'சரிபார்க்காத மறுபகுப்பாய்வு': 'Unvalidated reanalysis',
    'சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.': 'Try again shortly.',
    'செல்லாதது': 'Invalid',
    'செல்லுபடியாகும் நிர்வாகச் சான்றுகளை வழங்கவும்.': 'Provide valid administrator credentials.',
    'தரவுச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை': 'The data service is temporarily unavailable',
    'தேதி வரம்பு செல்லாது அல்லது 366 நாட்களை மீறுகிறது.': 'The date range is invalid or exceeds 366 days.',
    'தொடக்கமும் முடிவும் YYYY-MM-DD வடிவில் செல்லுபடியாக உள்ளிடப்பட வேண்டும்.': 'Enter valid start and end dates in YYYY-MM-DD format.',
    'நகல் பதிவு': 'Duplicate record',
    'நிகழ்வு தரவுத்தளம் தற்போது கிடைக்கவில்லை.': 'The event database is currently unavailable.',
    'நிர்வாக அங்கீகாரம் தேவை': 'Administrator authentication required',
    'நிர்வாக அணுகல் அமைக்கப்படவில்லை': 'Administrator access is not configured',
    'பருவநிலைச் சுட்டித் தரவுத்தளம் தற்போது கிடைக்கவில்லை.': 'The climate-index database is currently unavailable.',
    'மதிப்புகள் விடுபட்டவை': 'Missing values',
    'வரம்பிற்கு வெளியே': 'Out of range',
    'வானிலைச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை': 'The weather service is temporarily unavailable',
    'அக்டோபர்': 'October', 'ஆகஸ்ட்': 'August', 'ஏப்ரல்': 'April',
    'செப்டம்பர்': 'September', 'ஜனவரி': 'January', 'ஜூன்': 'June',
    'ஜூலை': 'July', 'டிசம்பர்': 'December', 'நவம்பர்': 'November',
    'பிப்ரவரி': 'February', 'மார்ச்': 'March', 'மே': 'May',
    'ஆராய்ச்சி நிலை': 'Research status',
    'இலக்கு இடத்திற்கான செயலில் உள்ள வானிலைத் தரவு இடம் இல்லை.': 'No active weather-data location is available for the target.',
    'கண்காணிக்கப்பட்ட நிகழ்வு மையப் புள்ளி இல்லை.': 'No observed event centre position is available.',
    'நிகழ்வு நேரத்துடன் பொருந்தும் தரச் சரிபார்க்கப்பட்ட உள்ளூர் ஈரப்பதம், மேகம், காற்று பதிவுகள் இல்லை.': 'No quality-checked local humidity, cloud, or wind records match the event time.',
    'அமைக்கப்பட்ட இடம் செயலில் உள்ள இடமாகத் தரவுத்தளத்தில் இல்லை.': 'The configured location is not active in the database.',
    'இந்த இடத்திற்கான வானிலைத் தரவு இன்னும் சேமிக்கப்படவில்லை.': 'Weather data has not yet been stored for this location.',
    'சமீபத்திய முன்னறிவிப்பு இன்னும் சரிபார்க்கப்படவில்லை; ஆராய்ச்சி முடிவாக மட்டும் பயன்படுத்தவும்.': 'The latest forecast has not been validated; use it only as a research result.',
    'தரவுத்தளம் தயாராக இல்லை; migration-ஐ இயக்கி மீண்டும் முயற்சிக்கவும்.': 'The database is not ready; run the migrations and try again.',
    'தற்போது நடைபெறுகிறது': 'In progress',
    'தரவுத்தளம் தயாராக இல்லாததால் சேமிப்பு நிலையைச் சரிபார்க்க முடியவில்லை. காட்டப்படும் காலங்கள் விதிகளிலிருந்து புதிதாகக் கணக்கிடப்பட்டவை.': 'Storage status cannot be checked because the database is not ready. Displayed periods were recalculated from the rules.',
    'கோரப்பட்ட தரவு மூலம் கிடைக்கவில்லை; சமீபத்திய மூலம் தேர்ந்தெடுக்கப்பட்டது.': 'The requested data source is unavailable; the latest source was selected.',
    'தேர்ந்தெடுத்த காலத்தில் வானிலைப் பதிவுகள் இல்லை.': 'No weather records exist for the selected period.',
    'ஆழ்ந்த காற்றழுத்தத் தாழ்வு': 'Deep depression',
    'கடந்த கண்காணிப்புப் பாதை': 'Past observed track',
    'காற்றழுத்தத் தாழ்வு': 'Depression',
    'குறைந்த காற்றழுத்தப் பகுதி': 'Low pressure area',
    'புயல்': 'Cyclonic storm',
    'மேலடுக்கு சுழற்சி': 'Upper air circulation',
    'கனமழை': 'Heavy rain',
    'தூறல் / இலேசான மழை': 'Drizzle / light rain',
    'மழையின்மை': 'No rain',
    'மிதமான மழை': 'Moderate rain',
    'சுக்கில பட்ச': 'Waxing fortnight',
    'கிருஷ்ண பட்ச': 'Waning fortnight',
    'பிரதமை': 'Prathamai', 'த்விதியை': 'Dvithiyai',
    'த்ருதியை': 'Thrithiyai', 'சதுர்த்தி': 'Chathurthi',
    'பஞ்சமி': 'Panchami', 'ஷஷ்டி': 'Shashti',
    'ஸப்தமி': 'Sapthami', 'அஷ்டமி': 'Ashtami',
    'நவமி': 'Navami', 'தசமி': 'Dasami',
    'ஏகாதசி': 'Ekadashi', 'துவாதசி': 'Dvadashi',
    'த்ரயோதசி': 'Trayodashi', 'சதுர்த்தசி': 'Chaturdashi',
    'பௌர்ணமி / அமாவாசை': 'Full moon / new moon',
    'ஆவணி': 'Aavani', 'புரட்டாசி': 'Purattasi',
    'ஐப்பசி': 'Aippasi', 'கார்த்திகை': 'Karthigai',
    'தை': 'Thai', 'மாசி': 'Maasi', 'பங்குனி': 'Panguni',
    'வைகாசி': 'Vaikasi',
    'கருவோட்டம்': 'Karuvottam',
    'கருவோட்டம் | மழை ஆய்வு தளம்': 'Karuvottam | Rain research site',
    'கருவோட்டம் ஆராய்ச்சி தளம்': 'Karuvottam research site',
    'கருவோட்டக் காலண்டர்': 'Karuvottam calendar',
    'கருவோட்டக் காலம்': 'Karuvottam period',
    'கருவோட்டத் தூண்டுதல் கணக்கீடுகள்': 'Karuvottam trigger calculations',
    'கருவோட்டம் / கணக்குப் பணியிடம்': 'Karuvottam / Calculation workspace',
    'கருவோட்டம் / கருவோட்டக் காலண்டர்': 'Karuvottam / Karuvottam calendar',
    'கருவோட்டம் / நிர்வாக நிலை': 'Karuvottam / Admin status',
    'கருவோட்டம் / மழை முன்னறிவிப்பு நாட்காட்டி': 'Karuvottam / Rain forecast calendar',
    'கருவோட்டம் / முகப்பு': 'Karuvottam / Home',
    'கருவோட்டம் / வானிலை நிகழ்வு ஆதார முகப்பு': 'Karuvottam / Weather event evidence',
    'கருவோட்டம் / வானிலைத் தரவு ஆய்வு': 'Karuvottam / Weather data inspection',
    'கருவோட்டம் / IOD / ENSO பருவநிலைப் பின்னணி': 'Karuvottam / IOD / ENSO climate context',
    'கருவோட்டம் + வானிலை — ஆய்வு மாதிரி': 'Karuvottam + weather — research model',
    'கருவோட்டம் மட்டும் — ஆய்வு மாதிரி': 'Karuvottam only — research model',
    'கருவோட்டம் சேர்த்த முறைகளுக்கு அடிப்படை முறையைவிட கூடுதல் முன்னறிவிப்புத் திறன் நிரூபிக்கப்படவில்லை.': 'Methods using Karuvottam have not shown better forecast skill than the baseline.',
    'ஆடி மற்றும் மார்கழி சாளரங்கள், சந்திரத் தூண்டுதல் மற்றும் விதிப் பதிவேடு.': 'Aadi and Margazhi windows, lunar triggers, and the rule log.',
    'மார்கழி கருவோட்டம்': 'Margazhi Karuvottam',
    'கோரிய பக்கம் கிடைக்கவில்லை • கருவோட்டம்': 'Requested page not found • Karuvottam',
    'நிர்வாக நிலை • கருவோட்டம்': 'Admin status • Karuvottam',
    'பணியிடம் • கருவோட்டம்': 'Workspace • Karuvottam',
    '“நவீன வானிலை மட்டும்” என்பது முந்தைய உள்ளூர் ERA5 மழையிலிருந்து உருவான பருவச் சராசரி. “இரண்டும் இணைந்தது” என்பது கருவோட்டச் சாளர வானிலை அம்சங்களைக் கொண்ட T6 ஆய்வு மாதிரி; நிகழ்வுப் பாதை அல்லது IOD/ENSO இதில் இன்னும் சேர்க்கப்படவில்லை. இவை பொதுப் பயன்பாட்டு மழை வாய்ப்புகள் அல்ல.': '“Modern weather only” is a seasonal mean from prior local ERA5 rainfall. “Both combined” is the T6 research model with Karuvottam window weather features; event tracks and IOD/ENSO are not yet included. These are not public rainfall probabilities.',
    'கருவோட்ட மூலம்': 'Karuvottam source',
    'கருவோட்டச் சாளரங்கள்': 'Karuvottam windows',
    'கருவோட்டம் முகப்பு': 'Karuvottam home',
    'தன்னியக்க துல்லிய மழை முன்னறிவிப்பு திட்டம்': 'Automated precise rain forecasting project',
    'முக்கிய உள்ளடக்கத்திற்குச் செல்ல': 'Skip to main content',
    'முக்கிய பக்கங்கள்': 'Main pages',
    'கருவோட்டம் முகப்பு': 'Karuvottam home',
    'சேவை இயங்குகிறது': 'Service active',
    'இடம் மற்றும் ஆண்டு தேர்வு': 'Location and year selection',
    'தற்போதைய ஆய்வு சூழல்': 'Current research context',
    'ஆய்வு இடம்': 'Research location',
    'ஆய்வு ஆண்டு': 'Research year',
    'முகப்பு': 'Home',
    'காலண்டர்': 'Calendar',
    'முன்னறிவிப்பு': 'Forecast',
    'அவதானிப்புகள்': 'Observations',
    'நிகழ்வுகள்': 'Events',
    'காலநிலை': 'Climate',
    'பணியிடம்': 'Workspace',
    'நிர்வாகம்': 'Admin',
    'காட்டு': 'Show',
    'ஆய்வு': 'Research',
    'தரவு': 'Data',
    'ஆண்டு': 'Year',
    'மாதம்': 'Month',
    'வாரம்': 'Week',
    'நாள்': 'Day',
    'நேரம்': 'Time',
    'தேதி': 'Date',
    'நிலை': 'Status',
    'முடிவு': 'Result',
    'தொடக்கம்': 'Start',
    'மூலம்': 'Source',
    'மூலத் தரவு': 'Source data',
    'மூலப் பதிவுகள்': 'Source records',
    'தரம்': 'Quality',
    'முறை': 'Method',
    'விதி': 'Rule',
    'வகை': 'Category',
    'மழை': 'Rain',
    'மேகம்': 'Cloud',
    'காற்று': 'Wind',
    'வெப்பநிலை': 'Temperature',
    'ஈரப்பதம்': 'Humidity',
    'உயரம்': 'Elevation',
    'மையம்': 'Centre',
    'இலக்கு': 'Target',
    'தமிழ்நாடு': 'Tamil Nadu',
    'கேரளம்': 'Kerala',
    'கர்நாடகம்': 'Karnataka',
    'இலங்கை': 'Sri Lanka',
    'அரபிக் கடல்': 'Arabian Sea',
    'வங்காள விரிகுடா': 'Bay of Bengal',
    'கிடைக்கிறது': 'Available',
    'தரவு இல்லை': 'No data',
    'வெளியிடப்படவில்லை': 'Not published',
    'சரிபார்க்கப்பட்டது': 'Verified',
    'செல்லுபடியாகும்': 'Valid',
    'செயலில் உள்ளது': 'Active',
    'அடுத்து வருகிறது': 'Coming next',
    'வரவிருக்கும்': 'Upcoming',
    'பௌர்ணமி': 'Full moon',
    'அமாவாசை': 'New moon',
    'ஆடி': 'Aadi',
    'மார்கழி': 'Margazhi',
    'சித்திரை': 'Chithirai',
    'ஆனி': 'Aani',
    'மழை முன்னறிவிப்பு நாட்காட்டி': 'Rain forecast calendar',
    'மழை நிகழ்தகவு': 'Rain probability',
    'மழை வகை': 'Rain category',
    'மழை வகை விதி': 'Rain category rule',
    'மழைக் கணிப்பு': 'Rain forecast',
    'மழை வாய்ப்பு சதவீதங்களும் செயல்பாட்டு மழை அளவு மாதிரியும் வெளியிடப்படவில்லை.': 'Rain probabilities and an operational rainfall amount model have not been published.',
    'ஆடி அடிப்படையிலான 180 நாள் முன்னறிவிப்பு': 'Aadi-based 180-day forecast',
    'மார்கழி அடிப்படையிலான 140 நாள் முன்னறிவிப்பு': 'Margazhi-based 140-day forecast',
    'ஆடி கருவோட்டம்': 'Aadi Karuvottam',
    'மார்கழி கருவோட்டம்': 'Margazhi Karuvottam',
    'ஆடி சுழற்சி': 'Aadi cycle',
    'மார்கழி சுழற்சி': 'Margazhi cycle',
    'மார்கழி அமாவாசை / பௌர்ணமி மாற்றம்': 'Margazhi new moon / full moon alternation',
    'தேர்ந்தெடுத்த சந்திர நிகழ்வு': 'Selected lunar event',
    'தேர்ந்தெடுக்கப்பட்ட ஆண்டு': 'Selected year',
    'தனிப்பயன் தமிழ் தேதி': 'Custom Tamil date',
    'தமிழ் மாதத் தொடக்கம்': 'Tamil month start',
    'திட்ட நாட்காட்டி': 'Project calendar',
    'சாளர நிலை': 'Window status',
    'சாளரத் தொடக்கம்': 'Window start',
    'சாளர முடிவு': 'Window end',
    'மூலச் சாளரம்': 'Source window',
    'கருவோட்டச் சாளரங்கள்': 'Karuvottam windows',
    'கருவோட்ட மூலம்': 'Karuvottam source',
    'காலவரிசை விதி': 'Timeline rule',
    'வானிலைத் தரவு ஆய்வு': 'Weather data inspection',
    'அவதானிப்புத் தரவு': 'Observation data',
    'கவனிப்பு தரவு': 'Observation data',
    'சமீபத்திய வானிலைத் தரவு': 'Recent weather data',
    'சமீபத்திய வானிலைப் பதிவு விவரங்கள்': 'Recent weather record details',
    'வானிலைத் தரவு மூலம்': 'Weather data source',
    'வானிலை வழங்குநர்': 'Weather provider',
    'தரவு மூலம்': 'Data source',
    'தரவு மூல நிலை': 'Data source status',
    'தரவு இடைவெளிகள்': 'Data gaps',
    'தரவு இல்லாத நாட்கள்': 'Days without data',
    'தரவு சுருக்கம்': 'Data summary',
    'தரவு ஆய்வு வடிகட்டி': 'Data inspection filters',
    'தரவு பராமரிப்பு': 'Data maintenance',
    'தரவுத்தளம்': 'Database',
    'தரவுத்தள நிலை': 'Database status',
    'சேமிக்கப்பட்ட மணிநேரப் பதிவுகள்': 'Stored hourly records',
    'சேமிக்கப்பட்ட மூலப் பதிவுகள்': 'Stored source records',
    'மணிநேர நிறைவு': 'Hourly coverage',
    'முழுமையாக விடுபட்ட மணிநேரங்கள்': 'Completely missing hours',
    'தொடர்ச்சியான மணிநேரங்கள் மட்டும் இணைக்கப்படும்': 'Only consecutive hours are joined',
    'பருவநிலை பின்னணி': 'Climate context',
    'பருவநிலை சுழற்சி கண்காணிப்பு': 'Climate cycle monitoring',
    'இந்தியப் பெருங்கடல் இருமுனைச் சுட்டி': 'Indian Ocean Dipole index',
    'வரலாற்று மழை': 'Historical rainfall',
    'வரலாற்று நிகழ்வு–மழை ஆய்வு': 'Historical event–rain analysis',
    'நிகழ்வு ஆய்வு': 'Event analysis',
    'நிகழ்வு காலவரிசை': 'Event timeline',
    'நிகழ்வு ஆதாரம்': 'Event evidence',
    'நிகழ்வு மூலங்கள்': 'Event sources',
    'நிகழ்வு தேர்வு': 'Event selection',
    'நிகழ்வு அறிவிப்புகளின் வரலாறு': 'Event advisory history',
    'புயல் பாதைகள், இலக்கு இடத் தாக்கம் மற்றும் வரலாற்று மழை தொடர்புகள்.': 'Storm tracks, target-location impact, and historical rainfall relationships.',
    'பாதை வரைபடம்': 'Track map',
    'பாதை வகைகள்': 'Track types',
    'அதிகாரப்பூர்வ முன்னறிவிப்பு': 'Official forecast',
    'மாதிரி வழிகாட்டுதல்': 'Model guidance',
    'கடந்த கண்காணிப்பு': 'Past observation',
    'இலக்கு இடம்': 'Target location',
    'மாதிரி ஒப்பீடு': 'Model comparison',
    'ஒரே காலப்பகுதியில் மாதிரி ஒப்பீடு': 'Model comparison over the same period',
    'ஆய்வு மதிப்பெண்': 'Research score',
    'ஆய்வு மதிப்பெண் விதி': 'Research score rule',
    'ஆய்வு ஆதாரங்கள்': 'Research evidence',
    'ஆதார இடைவெளிகள்': 'Evidence gaps',
    'ஆதார நிலை தெளிவாகக் காட்டப்படுகிறது': 'Evidence status is shown clearly',
    'முன்னறிவிப்பு இல்லை': 'No forecast',
    'முன்னறிவிப்பு ஓட்டம் இன்னும் உருவாக்கப்படவில்லை.': 'No forecast run has been generated yet.',
    'முன்னறிவிப்பு தடமறிதல்': 'Forecast traceability',
    'முன்னறிவிப்பு காட்சி கட்டுப்பாடுகள்': 'Forecast display controls',
    'வார முன்னறிவிப்பு': 'Weekly forecast',
    'மாத முன்னறிவிப்பு': 'Monthly forecast',
    'வெளியீடு நிறுத்திவைப்பு': 'Publication on hold',
    'வெளியீடு': 'Published',
    'தாக்க மதிப்பீடு': 'Impact assessment',
    'ஆதாரம் போதவில்லை': 'Insufficient evidence',
    'நிலை எச்சரிக்கைகள்': 'Status warnings',
    'நிர்வாக நிலை': 'Admin status',
    'நிர்வாகச் சேவை நிலை': 'Admin service status',
    'பாதுகாப்பு நிலை': 'Security status',
    'அணுகல் நிலை': 'Access status',
    'பாதுகாக்கப்பட்ட நிர்வாகப் பக்கம்': 'Protected admin page',
    'பதிவு விவரங்கள்': 'Record details',
    'பதிவு': 'Record',
    'மின்னஞ்சல் / செய்தி அறிவிப்புகள்': 'Email / message notifications',
    'அறிவிப்பு வரலாறு': 'Notification history',
    'அனுப்பல் பதிவுகள் இல்லை.': 'No delivery records.',
    'உங்கள் பங்கிற்கு அனுமதிக்கப்பட்ட பணியிடப் பக்கங்கள் மேலே உள்ளன.': 'The workspace pages available to your role are shown above.',
    'முகப்புப் பக்கத்திற்குத் திரும்புக': 'Return to home',
    'முகப்புப் பக்கத்திற்குத் திரும்பி மீண்டும் முயற்சிக்கவும்.': 'Return to home and try again.',
    'கோரிய பக்கம் கிடைக்கவில்லை': 'The requested page was not found',
    'பிழை': 'Error',
    'குறிப்பு எண்': 'Reference ID',
    'CSV பதிவிறக்கம்': 'Download CSV',
    'காலண்டரைத் திற': 'Open calendar',
    'தரவை ஆய்வு செய்': 'Inspect data',
    'நிகழ்வுகளைப் பார்': 'View events',
    'ஆய்வைத் திற': 'Open research',
    'விரிவான பதிவுகள்': 'Detailed records',
    'ஆடி 1 (சூன் 21) தொடங்கிய பின் முதலில் வரும் அமாவாசை அல்லது பௌர்ணமி நிகழ்வு நேரமே ஆடி தொடக்கம். மார்கழியில் அமாவாசை மற்றும் பௌர்ணமி ஆண்டுதோறும் மாறி மாறி பயன்படுத்தப்படும். தனிப்பயன் நாட்காட்டி விதி: 03-21 = சித்திரை 1; விதிப் பதிப்பு 2.0. இது இந்தத் திட்டத்தின் கணக்கீட்டு விதி மட்டுமே; அதிகாரப்பூர்வ தமிழ் நாட்காட்டி அல்ல.': 'The Aadi window begins at the exact time of the first new or full moon after Aadi 1 (June 21). Margazhi alternates between new and full moons each year. The custom calendar rule sets Chithirai 1 to March 21 (version 2.0). This is a project calculation rule, not an official Tamil calendar.',
    'சதுர்த்தசி offset, நான்கு நாள் நிலைபெறுதல், சூரிய உதய மாற்றம் அல்லது midnight fallback செயலில் உள்ள v2 விதியில் பயன்படுத்தப்படவில்லை.': 'The active v2 rule does not use a Chaturdashi offset, four-day stabilization, sunrise adjustment, or midnight fallback.',
    'ஆடி 1 தொடங்கிய பின் முதலில் வரும் அமாவாசை அல்லது பௌர்ணமியின் துல்லிய நேரத்தில் தொடங்கி 432 மணி நேரம் தொடரும்.': 'Starts at the exact time of the first new or full moon after Aadi 1 and continues for 432 hours.',
    '[தொடக்கம், முடிவு)': '[start, end)',
}

_catalog_path = Path(__file__).with_name('locales') / 'en.json'
if _catalog_path.exists():
    ENGLISH = {**json.loads(_catalog_path.read_text()), **ENGLISH}

_TEXT = re.compile(r'(?<=>)([^<>]+)(?=<)')
_ATTRIBUTE = re.compile(r'\b(aria-label|title|placeholder|data-label|alt)="([^"]*)"')
_MONTHS = {
    'சித்திரை': 'Chithirai', 'வைகாசி': 'Vaikasi', 'ஆனி': 'Aani',
    'ஆடி': 'Aadi', 'ஆவணி': 'Aavani', 'புரட்டாசி': 'Purattasi',
    'ஐப்பசி': 'Aippasi', 'கார்த்திகை': 'Karthigai',
    'மார்கழி': 'Margazhi', 'தை': 'Thai', 'மாசி': 'Maasi',
    'பங்குனி': 'Panguni',
}


def _dynamic(value):
    match = re.fullmatch(r'(.+) • கருவோட்டம்', value)
    if match and match[1] in ENGLISH:
        return f'{ENGLISH[match[1]]} • Karuvottam'
    match = re.fullmatch(r'கருவோட்டம் / (.+)', value)
    if match and match[1] in ENGLISH:
        return f'Karuvottam / {ENGLISH[match[1]]}'
    match = re.fullmatch(r'(ஜனவரி|பிப்ரவரி|மார்ச்|ஏப்ரல்|மே|ஜூன்|ஜூலை|ஆகஸ்ட்|செப்டம்பர்|அக்டோபர்|நவம்பர்|டிசம்பர்) (\d{4})', value)
    if match:
        return f'{ENGLISH[match[1]]} {match[2]}'
    match = re.fullmatch(r'வாரம் (\d+)', value)
    if match:
        return f'Week {match[1]}'
    match = re.fullmatch(r'நாள் (\d+)', value)
    if match:
        return f'Day {match[1]}'
    match = re.fullmatch(r'தரவுத்தளத்தில் சேமிக்கப்பட்டது · பதிவு #(\d+)', value)
    if match:
        return f'Stored in database · record #{match[1]}'
    match = re.fullmatch(r'சமீபத்திய வானிலைத் தரத்தின் தரநிலையைச் சரிபார்க்கவும்: (.+)', value)
    if match:
        return f'Check the quality of the latest weather data: {match[1]}'
    match = re.fullmatch(r'முந்தைய 24 மணிநேர உள்ளூர் மழை அளவீடு முழுமையில்லை \((\d+)/24 மணி\)\.', value)
    if match:
        return f'Local rainfall coverage for the past 24 hours is incomplete ({match[1]}/24 hours).'
    match = re.fullmatch(r'ஆண்டு செல்லாது; இயல்புநிலை (\d{4}) ஆண்டு காட்டப்படுகிறது\.', value)
    if match:
        return f'Invalid year; showing the default year {match[1]}.'
    match = re.fullmatch(r'ஆண்டு (\d{4})–(\d{4}) வரம்பில் இருக்க வேண்டும்; (\d{4}) ஆண்டு காட்டப்படுகிறது\.', value)
    if match:
        return f'Year must be between {match[1]} and {match[2]}; showing {match[3]}.'
    match = re.fullmatch(r'கடந்த கண்காணிப்புப் பாதை · (.+)', value)
    if match:
        return f'Past observed track · {match[1]}'
    match = re.fullmatch(r'(\d{4})–(\d{4}): (\d+) நிகழ்வுகள்; (\d+) முழுமையான முன்/நிகழ்வு/பின் மழைச் சாளரங்கள்\.', value)
    if match:
        return f'{match[1]}–{match[2]}: {match[3]} events; {match[4]} complete before/during/after rain windows.'
    match = re.fullmatch(r'(\d{4}) முதல் (\d+) சோதனை நிகழ்வுகள்: பயிற்சிச் சராசரி MAE ([\d.]+) மி\.மீ\./(\d+) மணி; தொடக்கத் தூர மாதிரி MAE ([\d.]+) மி\.மீ\./(\d+) மணி\.', value)
    if match:
        return f'Since {match[1]}, {match[2]} test events: training-mean MAE {match[3]} mm/{match[4]} h; initial-distance model MAE {match[5]} mm/{match[6]} h.'
    match = re.fullmatch(r'(\d{4})–(\d{4}) rolling holdout · ஒவ்வொரு முறைக்கும் அதே (\d+) நாள் பதிவுகள் · ஆதார விசை (.+)', value)
    if match:
        return f'{match[1]}–{match[2]} rolling holdout · the same {match[3]} daily records for each method · evidence key {match[4]}'
    match = re.fullmatch(r'(.+?) · (.+?) (மி\.மீ\.|கி\.மீ\./மணி) · மூலத் தரவு', value)
    if match:
        unit = 'mm' if match[3] == 'மி.மீ.' else 'km/h'
        return f'{match[1]} · {match[2]} {unit} · source data'
    match = re.fullmatch(r'(.+?) · (.+?) (%|°C) · மூலத் தரவு', value)
    if match:
        return f'{match[1]} · {match[2]} {match[3]} · source data'
    match = re.fullmatch(r'(.+?) முதல் (.+?) வரை · உள்ளூர் தேதிகள்', value)
    if match:
        return f'{match[1]} to {match[2]} · local dates'
    match = re.fullmatch(r'(\d+) ஆண்டிற்கான ஆடி மற்றும் மார்கழி கண்காணிப்புச் சாளரங்கள்', value)
    if match:
        return f'Aadi and Margazhi observation windows for {match[1]}'
    match = re.fullmatch(r'(\d+) நாட்கள்', value)
    if match:
        return f'{match[1]} days'
    match = re.fullmatch(r'([\d.]+) · கணக்கிடப்பட்டது', value)
    if match:
        return f'{match[1]} · calculated'
    match = re.fullmatch(r'(\d{2})-(\d{2}) = சித்திரை 1; விதிப் பதிப்பு ([\d.]+)\. இது அதிகாரப்பூர்வ தமிழ் நாட்காட்டி அல்ல\.', value)
    if match:
        return f'{match[1]}-{match[2]} = Chithirai 1; rule version {match[3]}. This is not an official Tamil calendar.'
    match = re.fullmatch(r'கடைசி கண்காணிப்பு நேரம்: (.+?)\. மையத் தூரம்: (.+?)\. முந்தைய புள்ளியிலிருந்து தூர மாற்றம்: (.+?) \(எதிர்மறை என்றால் அருகே வந்துள்ளது\)\.', value)
    if match:
        return f'Last observation: {match[1]}. Distance from centre: {match[2]}. Change from previous point: {match[3]} (negative means closer).'
    match = re.fullmatch(r'(\d+(?:\.\d+)?) (மி\.மீ\.|கி\.மீ\./மணி)', value)
    if match:
        return f'{match[1]} {"mm" if match[2] == "மி.மீ." else "km/h"}'
    match = re.fullmatch(r'(\d+) முழு நாட்கள்', value)
    if match:
        return f'{match[1]} complete days'
    match = re.fullmatch(r'(\d+) நாள் மழை முன்னறிவிப்பு விவரங்கள்', value)
    if match:
        return f'{match[1]}-day rain forecast details'
    match = re.fullmatch(r'(\d+) மணிநேரத் தரவு விடுபட்டுள்ளது; கீழே கால இடைவெளிகள் காட்டப்பட்டுள்ளன\.', value)
    if match:
        return f'{match[1]} hourly records are missing; time gaps are shown below.'
    match = re.fullmatch(r'Normalized வகை: (.+?) · தரம்: (.+?) · கடைசி அறிவிப்பு: (.+)', value)
    if match:
        return f'Normalized category: {match[1]} · quality: {match[2]} · last advisory: {match[3]}'
    match = re.fullmatch(r'தென்னிந்தியா நிலவரைபடத்தில் (.+?) நிகழ்வின் வகைப்படுத்தப்பட்ட பாதைகளும் இலக்கு இடமும்', value)
    if match:
        return f'Classified tracks of event {match[1]} and the target location on the South India map'
    match = re.fullmatch(r'· பெறப்பட்டது: (.+)', value)
    if match:
        return f'· Retrieved: {match[1]}'
    match = re.fullmatch(r'இந்தப் பாதை தற்போதைய நேரடி நிகழ்வு அல்ல\. கடைசி நிலைப் புள்ளி (.+?) மணி நேரம் பழையது\.', value)
    if match:
        return f'This track is not a current live event. The last position is {match[1]} hours old.'
    match = re.fullmatch(r'காலம்: (.+?) → (.+?) · தரம்: (.+)', value)
    if match:
        return f'Period: {match[1]} → {match[2]} · quality: {match[3]}'
    match = re.fullmatch(r'மீளுருவாக்க anchor: (\d{4}) = (அமாவாசை|பௌர்ணமி)\. தேர்ந்தெடுத்த ஆண்டு தனிப்படுத்திக் காட்டப்பட்டுள்ளது\.', value)
    if match:
        return f'Recurrence anchor: {match[1]} = {ENGLISH[match[2]]}. The selected year is highlighted.'
    match = re.fullmatch(r'மூல நேரக் குறிப்பு: (.+?) · பெறப்பட்டது: (.+)', value)
    if match:
        return f'Source time reference: {match[1]} · retrieved: {match[2]}'
    match = re.fullmatch(r'மூல நேரம்: (.+?) · பெறப்பட்டது: (.+)', value)
    if match:
        return f'Source time: {match[1]} · retrieved: {match[2]}'
    match = re.fullmatch(r'மூலப் பதிவுக் குறிப்புகள்: (.+)', value)
    if match:
        return f'Source record reference: {match[1]}'
    match = re.fullmatch(r'(.+?) (\d{1,2}) / (\d{4})', value)
    if match and match[1] in _MONTHS:
        return f'{_MONTHS[match[1]]} {match[2]} / {match[3]}'
    match = re.fullmatch(r'(அமாவாசை|பௌர்ணமி) — (.+)', value)
    if match:
        return f'{ENGLISH[match[1]]} — {match[2]}'
    match = re.fullmatch(r'(ஆடி|மார்கழி) · (\d{4})', value)
    if match:
        return f'{ENGLISH[match[1]]} · {match[2]}'
    match = re.fullmatch(r'(ஆடி|மார்கழி) கருவோட்டச் சாளரம் · (\d{4})', value)
    if match:
        return f'{ENGLISH[match[1]]} Karuvottam window · {match[2]}'
    match = re.fullmatch(r'(\d+(?:\.\d+)?) (நாள்|மணி|மீ|தொகுதிகள்|மணி நேரச் சாளரம்)', value)
    if match:
        unit = {'நாள்': 'days', 'மணி': 'hours', 'மீ': 'm',
                'தொகுதிகள்': 'modules', 'மணி நேரச் சாளரம்': 'hour window'}[match[2]]
        return f'{match[1]} {unit}'
    match = re.fullmatch(r'(\d+) நாள் / (\d+) மணி', value)
    if match:
        return f'{match[1]} days / {match[2]} hours'
    match = re.fullmatch(r'(\d+) நாள் முன்னறிவிப்பு', value)
    if match:
        return f'{match[1]}-day forecast'
    match = re.fullmatch(r'(\d+) நாள் வெளியீட்டைப் பார்க்க →', value)
    if match:
        return f'View {match[1]}-day forecast →'
    match = re.fullmatch(r'(\d{4}) கருவோட்டச் சுழற்சிகள்', value)
    if match:
        return f'{match[1]} Karuvottam cycles'
    match = re.fullmatch(r'மறுஆய்வு: (.+)', value)
    if match:
        return f'Reviewed: {match[1]}'
    match = re.fullmatch(r'(.+) முதல் (.+) வரை', value)
    if match:
        return f'From {match[1]} to {match[2]}'
    return None


def _translate(value):
    stripped = ' '.join(value.split())
    target = ENGLISH.get(stripped) or _dynamic(stripped)
    if target is None:
        return value
    return value[:len(value) - len(value.lstrip())] + target + value[len(value.rstrip()):]


def translate_ui_text(value):
    """Translate one complete UI message before it is joined with other text."""
    return _translate(value)


def selected_language():
    requested = request.args.get('lang')
    if requested in LANGUAGES:
        return requested
    saved = request.cookies.get('karuvottam_lang')
    return saved if saved in LANGUAGES else 'ta'


def translated_html(html):
    # Match complete text nodes and accessible attributes. Never alter links,
    # script content, or parts of longer Tamil sentences.
    def text_node(match):
        translated = _translate(match.group(0))
        return (escape(translated, quote=False)
                if translated != match.group(0) else match.group(0))

    html = _TEXT.sub(text_node, html)
    html = _ATTRIBUTE.sub(
        lambda match: f'{match.group(1)}="{escape(_translate(match.group(2)), quote=True)}"',
        html,
    )
    return html.replace('<html lang="ta">', '<html lang="en">', 1)


def language_links():
    args = [(key, value) for key, values in request.args.lists()
            if key != 'lang' for value in values]
    def url(language):
        query = urlencode([*args, ('lang', language)])
        return escape(f'{request.path}?{query}', quote=True)
    return url('ta'), url('en')


def language_control(language):
    tamil_url, english_url = language_links()
    label = 'Language' if language == 'en' else 'மொழி'
    return (
        '<nav class="language-switch" aria-label="' + label + '">'
        '<a href="' + tamil_url + '" lang="ta" hreflang="ta"' +
        (' aria-current="true"' if language == 'ta' else '') + '>தமிழ்</a>'
        '<a href="' + english_url + '" lang="en" hreflang="en"' +
        (' aria-current="true"' if language == 'en' else '') + '>English</a>'
        '</nav><script src="/static/language.js" defer></script>'
    )
