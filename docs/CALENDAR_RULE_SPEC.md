# Modified Tamil Calendar Rule

**Rule version:** 2.0

This is a project-defined computational calendar. It is not presented as the official Tamil calendar.

## Reference and year

- Chithirai 1 is March 21 by default.
- The reference month and day are configurable with `KARUVOTTAM_CHITHIRAI_REFERENCE=MM-DD`.
- A modified Tamil year is identified by the Gregorian year in which its Chithirai 1 occurs.
- For example, modified Tamil year 2026 begins on March 21, 2026 and ends immediately before March 21, 2027.
- Every conversion records the configured calendar rule version.

## Month boundaries

Each successive Tamil month begins on the same numerical day in the next Gregorian month. With the default March 21 reference, the boundaries are:

| Month | Start |
|---|---|
| சித்திரை | March 21 |
| வைகாசி | April 21 |
| ஆனி | May 21 |
| ஆடி | June 21 |
| ஆவணி | July 21 |
| புரட்டாசி | August 21 |
| ஐப்பசி | September 21 |
| கார்த்திகை | October 21 |
| மார்கழி | November 21 |
| தை | December 21 |
| மாசி | January 21 |
| பங்குனி | February 21 |

The month ends on the day immediately before the next boundary. Month lengths therefore follow the Gregorian intervals between boundaries. Panguni contains the leap day when the following Gregorian year is a leap year.

If a future reference uses a day that does not exist in a target month, that boundary is clamped to the target month's last day. The planned March 20–22 reference options do not require clamping.

## Conversion conventions

- Month and day numbers are one-based.
- Gregorian-to-Tamil conversion finds the latest Chithirai reference date not after the input date, then finds the containing half-open month interval.
- Tamil-to-Gregorian conversion rejects month or day values outside that year's calculated boundary.
- Round-trip conversion must reproduce every supported Gregorian input date.

## Important project consequence

Under this modified rule, Aadi 1 is June 21—the project-defined day after the northward solar movement/Mithuna transition ends—and Margazhi 1 is November 21. These dates define lunar-event search boundaries; the observation begins at the exact selected new-moon or full-moon time, not at month-start midnight.
