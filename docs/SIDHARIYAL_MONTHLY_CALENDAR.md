# Sidhariyal monthly calendar

The `/sidhariyal-calendar` route is a separate, Sunday-first monthly date view. It does not change the project's versioned `CalendarRule`, Karuvottam windows, stored forecasts, or historical evaluations.

## Source comparison

The [public monthly page](https://sidhariyal.org/sidhariyalmonthycalendar) renders month/day cells, Gregorian dates, a second conventional Tamil date, tithi and nakshatra times, and festival labels. Its calculation code is server-side and is not present in the delivered HTML or JavaScript. The public year views for 2026 and 2027 were inspected for day 1 of each Sidhariyal month. Both displayed this pattern:

| Sidhariyal month | Gregorian start |
|---|---|
| சித்திரை | 21 March |
| வைகாசி | 20 April |
| ஆனி | 21 May |
| ஆடி | 21 June |
| ஆவணி | 23 July |
| புரட்டாசி | 23 August |
| ஐப்பசி | 23 September |
| கார்த்திகை | 23 October |
| மார்கழி | 22 November |
| தை | 22 December |
| மாசி | 20 January of the following Gregorian year |
| பங்குனி | 19 February of the following Gregorian year |

For example, this gives **14 November 2026 = கார்த்திகை 23**, matching the site's daily date label. The existing project rule gives கார்த்திகை 25 on that date, so it remains a separate research rule.

## Forward calculation and limits

`SidhariyalCalendar` applies the observed civil-date pattern to any selected year from 2015 through 2100, computes month length from the next start, and lays out Sundays in the first column. It needs no online request or manual yearly update. The UI labels years outside 2026–2027 as **projections**, because the source has not published its underlying algorithm and future dates could differ. This version is `sidhariyal-public-2026-2027-pattern-v1`.

## Daily astronomy shown in the grid

The grid now calculates a sunrise tithi for each day. It divides Astronomy Engine's geocentric Moon–Sun ecliptic longitude difference into 30 consecutive 12° intervals: 15 growing-moon tithis and 15 waning-moon tithis. The first 14 names come from the existing project tithi vocabulary; interval 15 is பௌர்ணமி or அமாவாசை. The displayed end time is when the next 12° boundary occurs. A date can therefore have a different tithi later in the day; the label is explicitly the **sunrise tithi**.

The grid shows each sunrise tithi as a number and paksha, such as `9ம் வளர்பிறை`. It compares consecutive local sunrises, including the sunrise before the selected Tamil solar month begins. If the same tithi spans both sunrises, the later day is marked **மீண்டும்** (adhika tithi). If one or more complete tithis fall between the two sunrises, the later day lists them as **விடுபட்டது** (kshaya tithi). These markers describe sunrise-date assignment; they do not change the underlying 12° tithi boundaries or force a lunar cycle to fit the 29–32 days of a Tamil solar month.

New-moon and full-moon markers are calculated at exact geocentric phase instants and shown on the corresponding local civil date. Civil dawn and dusk are the times when the Sun's center crosses −6° altitude in the morning and evening. Sunrise and sunset are also shown separately. These daylight times use the selected location's latitude, longitude and elevation, with its configured time zone. If an event does not occur on a local date, a dash is displayed rather than a fabricated time. All times are local, in 24-hour format. The UI identifies the Astronomy Engine version used.

These astronomical values are independent calculations; the public site's tithi times may use different conventions, including a different ephemeris or location. Nakshatra, fast and festival rules remain unverified and are tracked by T10.4. No live page scraping is required for these daily calculations.

## Day-card interaction and window markers

The front of each day card keeps its date, daily tithi or phase-day name, and any event markers visible. `🌑` marks an exact new-moon event, `🌕` a full-moon event, `✦` a Karuvottam window start, and `◆` a window end. The start and end markers use the selected location's existing versioned Karuvottam window engine, not the Sidhariyal month pattern. The window end is exclusive (`[start, end)`).

On a new- or full-moon event date, the event badge shows the phase and its exact time without a duplicate “phase day” label. The separate tithi line uses a compact number and paksha, such as `1ம் வளர்பிறை`; it is calculated at sunrise as described above. For example, on 9 December 2026 the new moon and Margazhi Karuvottam both start at 06:22:31, but local sunrise is 06:23:43, when பிரதமை has begun. The window engine starts at the exact phase instant on that same local date; it does not move to the next sunrise. The generic marker labels are `கருவோட்டம் தொடக்கம்` and `கருவோட்டம் முடிவு`.

The **நேர விவரம்** button reveals the tithi end, civil dawn/dusk, sunrise/sunset, and exact window boundary time. **திரும்பு** restores the front. The controls are keyboard-focusable; focus moves to the visible button, and hidden details are removed from the accessibility tree. The flip animation is disabled when reduced motion is requested.

The same day cards form a seven-column grid on wide screens, a two-column layout on tablets, and a single-column list on phones. Each compact card includes its weekday because the desktop weekday header is hidden at those widths. Month/year controls and adjacent-month links wrap to the available width; the phone layout does not require horizontal calendar scrolling.
