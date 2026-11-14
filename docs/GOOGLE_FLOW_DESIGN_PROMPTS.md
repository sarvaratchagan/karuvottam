# Google Flow design tasks — Karuvottam

Use **Google Flow image generation** to create visual references for the existing Flask web app. Flow's output is a mockup image, not working UI code. For editable screens and frontend export, the same briefs can be used in Google Stitch. Work through F0 first, then create one Flow image per page. Upload a screenshot of the current page as a reference for each task so the content and structure remain recognizable.

## F0 — Shared visual system

**Description:** Establish a consistent visual language before designing individual screens.

**Flow prompt:**

> Create a flat, high-fidelity UI design reference for “கருவோட்டம்”, a Tamil-language weather observation and rain-research web app for South India. This is an evidence-first scientific product, not a generic weather forecast or emergency warning app. Art direction: calm, clear, trustworthy, warm off-white background, deep leaf green for navigation, monsoon teal for data, restrained amber for cautions, and red only for genuine failures. Use spacious typography that renders Tamil well, strong heading hierarchy, quiet card borders, generous whitespace, readable tables, and restrained weather-inspired iconography. Design reusable header, navigation, page title, location selector, date filters, status badges, source/provenance panels, empty states, and mobile controls. Keep data and uncertainty visible. Do not invent rain probability, official warnings, measurements, or improved model accuracy. No photograph, device frame, 3D perspective, or marketing hero. Produce a clean desktop design-system board with components and color/type examples, 16:9.

**Check:** Agree on colors, typography, spacing, badges, and navigation before continuing. Keep this image as a reference asset in Flow.

## F1 — Home dashboard `/`

**Description:** Make the location, active/next Karuvottam window, latest observation, forecast availability, and warnings easy to scan.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached current home screenshot, redesign the Tamil home dashboard as a flat, high-fidelity desktop web screenshot. Put the selected location and year in a compact, clear header. Lead with one prominent “கருவோட்ட நிலை” summary showing the current or next window and its exact dates. Below it, create four calm summary cards for location, window, latest weather observation, and latest forecast run. Show data age and quality beside the observation; show “முன்னறிவிப்பு இல்லை” clearly when no run exists. Place important warnings in a distinct but non-alarming panel. Give obvious paths to calendar, prediction, observations, events, and climate. Keep the Aadi 18-day and Margazhi 11-day research cycles visible without letting diagrams dominate the first screen. Use real-looking layout only, no invented measurements or forecast probabilities. Produce a 1440×900 desktop screenshot, no device frame.

## F2 — Karuvottam calendar `/calendar`

**Description:** Clarify the two seasonal windows and their calculation trace.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached calendar screenshot, redesign the Tamil Karuvottam calendar as a flat, high-fidelity desktop web screenshot. Give Aadi and Margazhi equal, distinct cards. In each card, make the selected lunar phase, exact local start, exact local end, and 18-day or 11-day duration the visual focus. Keep UTC time, source/version, data quality, and stored-versus-calculated status in a quieter expandable-looking evidence area. Show the five-year new-moon/full-moon alternation as a readable timeline. Include a year selector and a concise explanation that the start is inclusive and the end exclusive. Do not change the underlying calendar rule or imply this is an official Tamil calendar. Produce a 1440×900 desktop screenshot, no device frame.

## F3 — Rain-forecast calendar `/prediction`

**Description:** Improve navigation among Aadi/Margazhi and day/week/month views without overstating research outputs.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached prediction screenshot, redesign the Tamil rain-forecast calendar as a flat, high-fidelity desktop web screenshot. Create a clear hierarchy: season and 180/140-day range, Aadi/Margazhi switch, day/week/month view switch, then forecast content. Keep CSV download visible but secondary. Show a prominent research-status notice saying probability and rainfall amount are withheld when calibration or data are insufficient. In day view, make date, Tamil date, quality, method, and status scannable; use restrained status chips and a readable table. Include a deliberate “தரவு இல்லை” row style. Never draw rain icons, colored probability heatmaps, or numeric rainfall values where the app has no evidence. Produce a 1440×900 desktop screenshot, no device frame.

## F4 — Observation inspection `/observations`

**Description:** Make filters, coverage, source provenance, charts, and missing-data gaps understandable.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached observations screenshot, redesign the Tamil observation-data page as a flat, high-fidelity desktop web screenshot. Put start date, end date, and data-source filter in a compact filter bar. Immediately below, show coverage percentage, received/expected hours, raw record count, and interpolated count as clear summary metrics. Make source identity unmistakable: ERA5 and station/IoT measurements must not look merged. Design clean small-multiple time-series charts with labeled units, visible missing-hour gaps, and separate raw/interpolated markers. Place detailed hourly records in a readable table below. Show a caution when data are incomplete. Do not connect across missing data or imply interpolated points are measurements. Produce a 1440×900 desktop screenshot, no device frame.

## F5 — Event evidence dashboard `/events`

**Description:** Turn a long evidence page into a navigable story from source health to track to research limits.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached events screenshot, redesign the Tamil weather-event evidence dashboard as a flat, high-fidelity desktop web screenshot. Start with year/event selectors and a compact source-health strip with last attempt, last success, and stale status. Give the South India map a prominent but disciplined panel: clearly distinguish observed track, official forecast track, and model guidance using both line style and labels, with an accessible legend. Beside or below the map, show event summary, last valid position time, distance to selected location, and advisory timeline. Use section navigation to historical rain evidence, IOD/ENSO context, and model comparison. Preserve the explicit “insufficient evidence / withheld” research conclusion and explain that tracks are not local rain probabilities or official live warnings. No decorative storm path or invented alert severity. Produce a 1440×900 desktop screenshot, no device frame.

## F6 — Climate context `/climate`

**Description:** Make DMI/IOD and ONI/ENSO readable as dated context, not local forecasts.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached climate screenshot, redesign the Tamil IOD/ENSO climate-context page as a flat, high-fidelity desktop web screenshot. Create two parallel panels for DMI/IOD and ONI/ENSO. Show each latest value with its period start/end, classification, quality, source, issue/retrieval times, and a visible stale-data marker. Put source-poll health in a compact strip above. Use a modest recent-values table or restrained line chart that preserves exact period labels and units. Keep the explanation that these ocean indices are background context, not a village-level daily rain forecast, and that threshold labels are not official event declarations. Avoid dramatic climate colors or a local rain-probability graphic. Produce a 1440×900 desktop screenshot, no device frame.

## F7 — Account workspace `/workspace`

**Description:** Give signed-in users a clear landing page for the actions allowed by their role.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached workspace screenshot, redesign the Tamil signed-in workspace home as a flat, high-fidelity desktop web screenshot. Show the signed-in name and role in a modest identity area. Present only role-allowed destinations as useful, well-labeled cards: public forecast/observations for everyone, research for researcher/admin, data maintenance for data-maintainer/admin, and accounts/admin for admin. Explain each destination in one short line. Keep the navigation calm and avoid implying that a viewer can edit data. Make the active role and access boundaries understandable without showing secrets. Produce a 1440×900 desktop screenshot, no device frame.

## F8 — Research workspace `/workspace/research`

**Description:** Make research links and evidence caveats useful to an analyst.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached research-workspace screenshot, redesign a Tamil researcher page as a flat, high-fidelity desktop web screenshot. Lead with data availability and current research warnings. Provide clear routes to event evidence, climate context, and forecast CSV. Use compact evidence cards with source, period, and status, plus a prominent note when model results are withheld or not calibrated. This page is for inspection, not publication of an unsupported rain probability. Avoid fake metrics or new controls that do not exist in the product. Produce a 1440×900 desktop screenshot, no device frame.

## F9 — Data-maintenance workspace `/workspace/data`

**Description:** Surface source health and data freshness for operators.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached data-workspace screenshot, redesign a Tamil data-maintenance page as a flat, high-fidelity desktop web screenshot. Show IBTrACS active, DMI, and ONI as separate source-status rows with health, last attempt, last success, and stale/failed indicators. Put links to observations and event sources nearby. Make failures noticeable and actionable-looking without inventing web buttons for CLI-only imports or retries. Distinguish missing state, overdue polling, and last-attempt failure with text and icons, not color alone. Produce a 1440×900 desktop screenshot, no device frame.

## F10 — Account list `/workspace/accounts`

**Description:** Make account status and role assignments clear to administrators without exposing secrets.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached accounts-workspace screenshot, redesign the Tamil administrator account-list page as a flat, high-fidelity desktop web screenshot. Show username, role, and enabled/disabled state in a clean accessible list or table. Make the environment bootstrap administrator concept clear in a small note. Show the existing operator CLI guidance as a help panel rather than drawing nonfunctional account-edit forms. Never display password hashes, tokens, or example real credentials. Produce a 1440×900 desktop screenshot, no device frame.

## F11 — Admin status `/admin`

**Description:** Prioritize service health, actionable warnings, and notification delivery failures.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached admin screenshot, redesign the protected Tamil administrator status page as a flat, high-fidelity desktop web screenshot. Put database readiness, location record, weather provider, authentication state, and important warnings in an easy-to-scan service-health summary. Add a separate notification-delivery section showing channel, source, status, attempt count, last error type, and time. Failed deliveries should stand out without showing webhook URLs, passwords, API keys, or message bodies. Present CLI setup/retry guidance in a quiet help panel. The page currently inspects status; do not invent web mutation controls. Produce a 1440×900 desktop screenshot, no device frame.

## F12 — Error page

**Description:** Make failures understandable and provide a safe path back.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached error-page screenshot, redesign the Tamil error page as a flat, high-fidelity web screenshot. Show a clear error title, one plain-language explanation, a readable request/reference ID, and an obvious return-home link. Use a calm visual treatment for ordinary input errors and a stronger but restrained treatment for service failure. Do not show traceback, server paths, credentials, or made-up recovery promises. Produce a 1440×900 desktop screenshot, no device frame.

## F13 — Offline page

**Description:** Clearly state that current data cannot be fetched while keeping the installed app usable.

**Flow prompt:**

> Using the approved Karuvottam design system and the attached offline-page screenshot, redesign the Tamil offline page as a flat, high-fidelity web screenshot. Use a simple connection icon, the heading “இணைய இணைப்பு இல்லை”, a short statement that current weather data and rain research cannot be fetched, and one prominent “மீண்டும் முயற்சி செய்” action. The screen must never show cached forecast values as current. Keep it lightweight so it works when only the pre-cached shell is available. Produce a 1440×900 desktop screenshot, no device frame.

## Mobile follow-up prompt for every task

After approving a desktop image, use that image as a reference and run this follow-up in Flow:

> Create a separate 390×844 mobile version of this exact Karuvottam page. Keep the approved visual system, Tamil hierarchy, and all scientific caveats. Reflow into a single column with readable type, 44 px touch controls, no horizontal page overflow, visible status text, and charts/tables adapted for small screens. Preserve the same real features and states. Do not place the design inside a phone mockup. Do not invent data or remove warnings to gain space.

For implementation, compare each image against the current page and use the image for layout/style only. Flow-generated Tamil text and numbers must be checked against the application; the app's real data, rules, source times, quality labels, and withheld outputs remain authoritative. Verify keyboard access, visible focus, semantic headings, contrast, and target size against [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
