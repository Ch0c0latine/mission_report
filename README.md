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
