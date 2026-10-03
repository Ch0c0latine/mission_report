# mission_report
Odoo module for Mission Report and leave management - daily Timesheet management with calendar view, monthly reports and client deliverables

## Invoicing the days

When a monthly activity report is validated, its days per mission are added to
the **delivered quantity** of the order line the mission's project belongs to
(the project's sales order item, and the other service lines of the order that
carry the project). Nothing is typed by hand: the next invoice takes the days
delivered since the last one. A report sent back to draft takes its days back.
A daily task does the same for every validated report, as a safety net.

Needs `sale_project`. Lines whose quantity is not delivered by hand (for
example from timesheets) are left alone.

## Several orders for one mission (volets)

A mission has one project per order, but orders follow one another on the same
project. Each order carries a start and an end date (under the project, in the
invoicing group). As soon as a project has several orders, the dates are
required and must not overlap; when they are empty they are read from the title
of the order's note ("Volet 2 : période du 01/10/2026 au 31/03/2027"). Validated
days and re-invoiced expenses go to the order whose period holds their date.

**New volet** (button on the order) copies the order, with the same customer,
project and conditions, on new dates. The working days of the people on the
mission (their work schedule, public holidays and the time off already booked
deducted) give the quantity of the day lines, and the title and the monthly
forecast of the note are rewritten. The public holidays of the years concerned
must be entered first (Activité > Configuration > Generate French public
holidays).

## IGD

The monthly average of IGD agreed on a mission (administrators only) drives
"Generate IGD" in Expenses: lodging first, then meals, up to the amount, with
catch-up of the earlier months. The result window says what was created (the
detail by month is shown to administrators only) or why nothing was, with a link
to the person's entries of that month.

## Overview

The overview opens on the year. A click on an entry opens it; a click on a day
or a drag over several days creates one; in the yearly view the entries of a day
show on hover and a month title leads to that month. The "Year" button of the
monthly view goes back.
