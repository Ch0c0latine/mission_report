# -*- coding: utf-8 -*-
"""Excel templates for activity reports.

A template is a workbook plus a list of mappings, as in expense_scan: a cell
("B3") receives a header value once, a column letter ("A") receives a value
on every line of a block. On top of that, an activity report is a month
grid: one column per day, from ``first_day_column`` on, and two blocks of
lines, missions then time off.

The template's blocks are resized to exactly the report's lines; formulas
below a block (totals) follow. The day columns of days the month does not
have (29 to 31) are emptied and hidden.

Users download the blank workbook, lay it out in Excel or LibreOffice (logo,
colours, extra rows or columns), then upload it back.
"""
import base64
import io
import logging
import re
import zipfile
from copy import copy

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: Values a line column can receive.
LINE_VALUES = [
    ('label', "Client, or time off type"),
    ('client', "Client"),
    ('project', "Mission"),
    ('leave_type', "Time off type"),
    ('total', "Line total (days)"),
]
#: Values a header cell can receive.
HEADER_VALUES = [
    ('employee', "Employee"),
    ('company', "Company"),
    ('month', "Month (first day, as a date)"),
    ('month_label', "Month (text)"),
    ('potential_days', "Working days"),
    ('status', "Status"),
    ('submit_date', "Submission date"),
    ('validate_date', "Validation date"),
    ('client', "Client (client report)"),
    ('mission_total', "Mission days"),
    ('absence_total', "Time off days"),
    ('total', "Total days"),
]
VALUES = LINE_VALUES + [item for item in HEADER_VALUES
                        if item[0] not in {key for key, _label in LINE_VALUES}]
CELL_RE = re.compile(r"^([A-Z]{1,3})([0-9]*)$")
#: Reference ("$L$70") or range ("L8:L68") in a formula of the same sheet.
CELL_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_!'.$])(\$?[A-Z]{1,3}\$?)(\d+)"
    r"(?::(\$?[A-Z]{1,3}\$?)(\d+))?(?![0-9A-Za-z_(])")
MAX_DAYS = 31


def _import_openpyxl():
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as error:
        raise UserError(_("The openpyxl library is missing on the server.")) from error
    return openpyxl


class MissionActivityReportTemplate(models.Model):
    _name = 'mission.activity.report.template'
    _description = "Activity report Excel template"
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company")
    kind = fields.Selection(
        [('internal', "Internal (missions and time off)"), ('client', "Client (missions of one client)")],
        required=True, default='internal',
        help="A client report is exported once per client of the month.")
    file = fields.Binary(string="Excel file", attachment=True)
    filename = fields.Char()
    sheet_name = fields.Char(string="Sheet", help="Empty: the first sheet of the workbook.")
    first_day_column = fields.Char(
        string="Day 1 column", required=True, default='D',
        help="Column of the 1st of the month; the next 30 columns hold the other days.")
    week_row = fields.Integer(string="Week numbers row", help="0: none.")
    day_row = fields.Integer(string="Day numbers row", help="0: none.")
    weekday_row = fields.Integer(string="Weekdays row", help="0: none.")
    mission_first_row = fields.Integer(string="First mission row", required=True, default=10)
    mission_last_row = fields.Integer(string="Last mission row", required=True, default=12)
    absence_first_row = fields.Integer(
        string="First time off row", help="0: no time off block (client reports).")
    absence_last_row = fields.Integer(string="Last time off row")
    color_days = fields.Boolean(
        string="Colour the days", default=True,
        help="Fills the day columns of weekends, public holidays and time off.")
    weekend_color = fields.Char(default='D9D9D9')
    holiday_color = fields.Char(default='FFF2CC')
    absence_color = fields.Char(default='C6EFCE')
    cell_ids = fields.One2many(
        'mission.activity.report.template.cell', 'template_id', string="Mappings", copy=True)
    note = fields.Text()

    @api.constrains('mission_first_row', 'mission_last_row', 'absence_first_row',
                    'absence_last_row', 'first_day_column')
    def _check_layout(self):
        for template in self:
            if template.mission_first_row < 1 or template.mission_last_row < template.mission_first_row:
                raise UserError(_("The mission rows of template “%s” are inconsistent.", template.name))
            if template.absence_first_row and (
                    template.absence_last_row < template.absence_first_row
                    or template.absence_first_row <= template.mission_last_row):
                raise UserError(_("The time off rows of template “%s” must come after the mission rows.",
                                  template.name))
            if not CELL_RE.match((template.first_day_column or '').strip().upper()) \
                    or CELL_RE.match(template.first_day_column.strip().upper()).group(2):
                raise UserError(_("“Day 1 column” takes a column letter, such as D."))

    # ------------------------------------------------------------------
    # Blank workbook
    # ------------------------------------------------------------------

    def action_generate_file(self):
        """Blank workbook laid out after the template's settings and mappings."""
        for template in self:
            template.write({
                'file': base64.b64encode(template._blank_workbook()),
                'filename': "%s.xlsx" % re.sub(r'[\\/:*?"<>|]+', '-', template.name),
            })
        return True

    @api.model
    def _fill_blank_files(self):
        """Blank workbook of the shipped templates that have none yet."""
        try:
            import openpyxl  # noqa: F401, PLC0415
        except ImportError:
            _logger.warning("openpyxl missing: activity report templates shipped without workbook")
            return
        for xmlid in ('mission_report.activity_report_template_internal',
                      'mission_report.activity_report_template_client'):
            template = self.env.ref(xmlid, raise_if_not_found=False)
            if template and not template.file:
                template.action_generate_file()

    def _blank_workbook(self):
        self.ensure_one()
        openpyxl = _import_openpyxl()
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: PLC0415
        from openpyxl.utils import column_index_from_string, get_column_letter  # noqa: PLC0415

        labels = dict(VALUES)
        header_labels = dict(HEADER_VALUES)
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = (self.sheet_name or _("Activity"))[:31]
        thin = Side(style='thin', color='808080')
        box = Border(left=thin, right=thin, top=thin, bottom=thin)
        title_fill = PatternFill('solid', start_color='DDE7F0')
        bold = Font(bold=True)
        center = Alignment(horizontal='center', vertical='center')

        sheet['A1'] = _("Monthly activity report")
        sheet['A1'].font = Font(bold=True, size=14)

        # Header: each value, and its label in the cell on its left.
        for cell_map in self.cell_ids.filtered(lambda c: c.kind == 'header' and c.value):
            cell = sheet[cell_map.cell.strip().upper()]
            if cell.column > 1:
                label = sheet.cell(row=cell.row, column=cell.column - 1)
                label.value = header_labels.get(cell_map.value, labels[cell_map.value])
                label.font = bold
            if cell_map.value in ('month', 'submit_date', 'validate_date'):
                cell.number_format = 'DD/MM/YYYY'

        first_day = column_index_from_string(self.first_day_column.strip().upper())
        day_columns = range(first_day, first_day + MAX_DAYS)
        line_columns = {column_index_from_string(c.cell.strip().upper()): c
                        for c in self.cell_ids if c.kind == 'line' and c.value}
        title_row = self.mission_first_row - 1
        for row, title in ((self.week_row, _("Week")), (self.day_row, _("Day")),
                           (self.weekday_row, '')):
            if row and first_day > 1 and title:
                sheet.cell(row=row, column=first_day - 1, value=title).font = bold
            for column in (day_columns if row else ()):
                cell = sheet.cell(row=row, column=column)
                cell.font = bold
                cell.alignment = center
                cell.border = box
        # Column titles above the mission lines, unless a day row is there.
        if title_row >= 1:
            for column, cell_map in line_columns.items():
                if cell_map.block != 'absence':
                    head = sheet.cell(row=title_row, column=column, value=labels[cell_map.value])
                    head.font = bold
                    head.fill = title_fill
                    head.border = box

        blocks = [('mission', self.mission_first_row, self.mission_last_row)]
        if self.absence_first_row:
            section = sheet.cell(row=self.absence_first_row - 1, column=1, value=_("Time off"))
            section.font = bold
            blocks.append(('absence', self.absence_first_row, self.absence_last_row))
        for block, first, last in blocks:
            for row in range(first, last + 1):
                for column in list(day_columns) + [c for c, m in line_columns.items()
                                                   if m.block in (block, 'both')]:
                    cell = sheet.cell(row=row, column=column)
                    cell.border = box
                    if column in day_columns:
                        cell.alignment = center

        # Total line: day by day, sum of the blocks above.
        total_row = blocks[-1][2] + 1
        sheet.cell(row=total_row, column=1, value=_("Total")).font = bold
        for column in day_columns:
            letter = get_column_letter(column)
            ranges = ["%s%s:%s%s" % (letter, first, letter, last) for _block, first, last in blocks]
            cell = sheet.cell(row=total_row, column=column,
                              value="=%s" % "+".join("SUM(%s)" % item for item in ranges))
            cell.font = bold
            cell.border = box
            cell.alignment = center
            sheet.column_dimensions[letter].width = 4.5
        for column, cell_map in line_columns.items():
            sheet.column_dimensions[get_column_letter(column)].width = \
                7 if cell_map.value == 'total' else 28
        sheet.freeze_panes = sheet.cell(row=self.mission_first_row, column=first_day)

        output = io.BytesIO()
        book.save(output)
        return output.getvalue()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export(self, report, partner_id=None):
        """The template's workbook, filled with one report."""
        self.ensure_one()
        openpyxl = _import_openpyxl()
        from openpyxl.styles import PatternFill  # noqa: PLC0415
        from openpyxl.utils import column_index_from_string, get_column_letter  # noqa: PLC0415
        if not self.file:
            raise UserError(_("Template “%s” has no Excel file.", self.name))

        data = report._get_render_data(partner_id=partner_id if self.kind == 'client' else None)
        book = openpyxl.load_workbook(io.BytesIO(base64.b64decode(self.file)))
        sheet = book[self.sheet_name] if self.sheet_name else book.worksheets[0]
        first_day = column_index_from_string(self.first_day_column.strip().upper())
        days = data['days']

        blocks = [('mission', self.mission_first_row, self.mission_last_row, data['missions'])]
        if self.absence_first_row:
            blocks.append(('absence', self.absence_first_row, self.absence_last_row,
                           data['absences'] if self.kind == 'internal' else []))
        # Resize bottom-up: resizing a block leaves the rows above it in
        # place. A block empty of lines keeps one blank row.
        for _block, first, last, lines in sorted(blocks, key=lambda item: -item[1]):
            self._resize_block(sheet, first, last, max(len(lines), 1))
        # Then fill top-down, each block pushed by the growth of those above.
        filled_rows = []
        shift = 0
        for block, first, last, lines in blocks:
            count = max(len(lines), 1)
            size = last - first + 1
            first += shift
            shift += count - size
            columns = {column_index_from_string(c.cell.strip().upper()): c.value
                       for c in self.cell_ids
                       if c.kind == 'line' and c.value and c.block in (block, 'both')}
            for index in range(count):
                row = first + index
                line = lines[index] if index < len(lines) else None
                for column, value in columns.items():
                    sheet.cell(row=row, column=column).value = \
                        self._line_value(line, value) if line else None
                for offset in range(MAX_DAYS):
                    cell = sheet.cell(row=row, column=first_day + offset)
                    cell.value = line['values'][offset] if line and offset < len(days) else None
            filled_rows.append((first, first + count - 1))

        for cell_map in self.cell_ids.filtered(lambda c: c.kind == 'header' and c.value):
            sheet[cell_map.cell.strip().upper()].value = self._header_value(report, data, cell_map.value)

        # Day header rows, and the days the month does not have.
        rows = [row for row in (self.week_row, self.day_row, self.weekday_row) if row]
        previous_week = None
        for offset in range(MAX_DAYS):
            column = first_day + offset
            letter = get_column_letter(column)
            if offset >= len(days):
                for row in rows:
                    sheet.cell(row=row, column=column).value = None
                sheet.column_dimensions[letter].hidden = True
                continue
            day = days[offset]
            if self.week_row:
                sheet.cell(row=self.week_row, column=column).value = \
                    day['week'] if day['week'] != previous_week else None
                previous_week = day['week']
            if self.day_row:
                sheet.cell(row=self.day_row, column=column).value = day['day']
            if self.weekday_row:
                sheet.cell(row=self.weekday_row, column=column).value = day['weekday_label']
            if self.color_days:
                color = self._day_color(day)
                if color:
                    fill = PatternFill('solid', start_color=color)
                    for row in rows:
                        sheet.cell(row=row, column=column).fill = fill
                    for first, last in filled_rows:
                        for row in range(first, last + 1):
                            sheet.cell(row=row, column=column).fill = fill

        output = io.BytesIO()
        book.save(output)
        return output.getvalue()

    def _day_color(self, day):
        if day['weekend']:
            return self.weekend_color
        if day['holiday']:
            return self.holiday_color
        if day['absence'] and self.kind == 'internal':
            return self.absence_color
        return False

    @api.model
    def _line_value(self, line, value):
        if value == 'label':
            return line.get('label') or None
        if value == 'client':
            return line.get('partner') or None
        if value == 'project':
            return line.get('project') or None
        if value == 'leave_type':
            return line.get('label') if 'leave_type_id' in line else None
        if value == 'total':
            return line.get('total')
        return None

    def _header_value(self, report, data, value):
        return {
            'employee': data['employee'],
            'company': data['company'],
            'month': fields.Date.to_date(data['date_from']),
            'month_label': data['month_label'],
            'potential_days': data['potential_days'],
            'status': data['status'],
            'submit_date': report.submit_date or None,
            'validate_date': report.validate_date or None,
            'client': data.get('partner') or None,
            'mission_total': data['mission_total'],
            'absence_total': data['absence_total'] if self.kind == 'internal' else None,
            'total': data['mission_total'] + (data['absence_total'] if self.kind == 'internal' else 0),
        }.get(value)

    @api.model
    def _resize_block(self, sheet, first, last, count):
        """Make the block span exactly ``count`` rows, from ``first``.

        Rows are added or removed at the end of the block. openpyxl moves the
        cells but neither row heights, merged cells, nor the ranges of the
        formulas further down: they are shifted here, so the total line keeps
        its look and sums exactly the block's lines. New rows take the style
        of the block's first row.
        """
        delta = count - (last - first + 1)
        if not delta:
            return
        body = {c.column: copy(c._style) for c in sheet[first] if c.has_style}
        height = sheet.row_dimensions[first].height
        new_last = last + delta
        below = {row: (dim.height, dim.hidden)
                 for row, dim in sheet.row_dimensions.items() if row > last}
        if delta > 0:
            sheet.insert_rows(last + 1, delta)
        else:
            sheet.delete_rows(new_last + 1, -delta)
        for row in [row for row in sheet.row_dimensions if row > new_last]:
            del sheet.row_dimensions[row]
        for row, (row_height, hidden) in below.items():
            dimension = sheet.row_dimensions[row + delta]
            dimension.height = row_height
            dimension.hidden = hidden
        for row in range(last + 1, new_last + 1):
            sheet.row_dimensions[row].height = height
            for column, style in body.items():
                sheet.cell(row=row, column=column)._style = copy(style)

        for merged in list(sheet.merged_cells.ranges):
            if merged.min_row > last:
                merged.shift(0, delta)
            elif merged.max_row > new_last:
                sheet.merged_cells.remove(merged)

        def shift(match):
            start = int(match.group(2))
            text = "%s%s" % (match.group(1), start + delta if start > last else start)
            if match.group(3):
                end = int(match.group(4))
                if end > last:
                    end += delta
                elif end == last and start <= last:
                    end = new_last  # range down to the bottom of the block
                text += ":%s%s" % (match.group(3), end)
            return text

        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    cell.value = CELL_REF_RE.sub(shift, cell.value)


class MissionActivityReportTemplateCell(models.Model):
    _name = 'mission.activity.report.template.cell'
    _description = "Activity report template mapping"
    _order = 'kind desc, id'

    template_id = fields.Many2one(
        'mission.activity.report.template', required=True, ondelete='cascade')
    cell = fields.Char(
        string="Column or cell", required=True,
        help="A column letter (“A”): the value of every line of the block. "
             "A cell (“B3”): a header value, written once. For a merged cell, "
             "its top-left cell.")
    kind = fields.Selection(
        [('line', "Lines"), ('header', "Header")], compute='_compute_kind', store=True)
    block = fields.Selection(
        [('mission', "Missions"), ('absence', "Time off"), ('both', "Both")],
        default='both', help="For a column: the block(s) of lines it applies to.")
    value = fields.Selection(VALUES, required=True)

    @api.depends('cell')
    def _compute_kind(self):
        for cell_map in self:
            match = CELL_RE.match((cell_map.cell or '').strip().upper())
            cell_map.kind = 'header' if match and match.group(2) else 'line'

    @api.constrains('cell', 'value')
    def _check_cell(self):
        line_keys = {key for key, _label in LINE_VALUES}
        header_keys = {key for key, _label in HEADER_VALUES}
        for cell_map in self:
            if not CELL_RE.match((cell_map.cell or '').strip().upper()):
                raise UserError(_("“%s”: a column letter (A) or a cell (B3).", cell_map.cell))
            allowed = header_keys if cell_map.kind == 'header' else line_keys
            if cell_map.value not in allowed:
                raise UserError(_(
                    "“%(value)s” cannot go in %(cell)s.",
                    value=dict(VALUES)[cell_map.value], cell=cell_map.cell))


class MissionActivityReportExport(models.TransientModel):
    _name = 'mission.activity.report.export'
    _description = "Export activity reports to Excel"

    report_ids = fields.Many2many('mission.activity.report', string="Reports", required=True)
    template_id = fields.Many2one(
        'mission.activity.report.template', string="Template", required=True,
        default=lambda self: self.env['mission.activity.report.template'].search([], limit=1))

    def action_export(self):
        """One workbook per report (per report and client for a client
        template); several workbooks come as a zip archive."""
        self.ensure_one()
        files = []
        for report in self.report_ids:
            stem = re.sub(r'[\\/:*?"<>|]+', '-', "%s - %s" % (self.template_id.name, report.name))
            if self.template_id.kind == 'client':
                for partner_id in report._get_client_partner_ids():
                    partner = self.env['res.partner'].browse(partner_id).display_name \
                        if partner_id else _("No client")
                    files.append(("%s - %s.xlsx" % (stem, re.sub(r'[\\/:*?"<>|]+', '-', partner)),
                                  self.template_id._export(report, partner_id)))
            else:
                files.append(("%s.xlsx" % stem, self.template_id._export(report)))
        if not files:
            raise UserError(_("These reports hold no mission to export."))
        if len(files) == 1:
            name, content = files[0]
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file_name, file_content in files:
                    archive.writestr(file_name, file_content)
            name, content, mimetype = _("Activity reports.zip"), buffer.getvalue(), 'application/zip'
        attachment = self.env['ir.attachment'].create({
            'name': name,
            'raw': content,
            'mimetype': mimetype,
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
