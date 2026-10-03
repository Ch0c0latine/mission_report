# -*- coding: utf-8 -*-
"""Autosuffisance : le module ne requiert pas expense_scan et s'en sert quand il est là."""
import importlib.util
import os
import re
from unittest.mock import patch

from odoo import Command
from odoo.modules.module import get_manifest
from odoo.tests.common import TransactionCase

from odoo.addons.mission_report.models import account_move as account_move_module

from .test_sale_delivery import TestSaleDelivery

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _migration(version, name):
    path = os.path.join(MODULE_DIR, 'migrations', version, name)
    spec = importlib.util.spec_from_file_location('mission_report_migration_%s' % version.replace('.', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_expense_scan(env):
    # Les points d'accroche sont déclarés ici : leur présence ne dit pas si expense_scan est là.
    return 'expense_scan_invoice_id' in env['hr.expense']._fields


class TestIndependance(TransactionCase):

    def test_dependances(self):
        """Les applications d'Odoo seulement, sans expense_scan, même indirectement."""
        depends = get_manifest('mission_report')['depends']
        self.assertNotIn('expense_scan', depends)
        for name in ('hr_holidays', 'project', 'sale_project', 'hr_expense'):
            self.assertIn(name, depends)
        module = self.env['ir.module.module']._get('mission_report')
        upstream = module.upstream_dependencies(exclude_states=('uninstallable',)).mapped('name')
        self.assertIn('hr_expense', upstream)
        self.assertNotIn('expense_scan', upstream)

    def test_aucune_reference_a_expense_scan(self):
        """Ni xmlid, ni import, ni modèle, ni champ d'expense_scan dans le code et les données.

        Seuls les points d'accroche (méthodes ``_expense_scan_*`` et ``expense_scan_sheet_files``,
        appelée sous ``hasattr``) le nomment.
        """
        pattern = re.compile(r"expense_scan\.|odoo\.addons\.expense_scan|expense\.scan\.|name=\"expense_scan_")
        found = []
        for folder in ('models', 'views', 'data', 'security', 'report', 'wizard', os.path.join('static', 'src')):
            for root, _dirs, files in os.walk(os.path.join(MODULE_DIR, folder)):
                for name in files:
                    if not name.endswith(('.py', '.xml', '.csv', '.js')):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding='utf-8') as source:
                        found += ["%s: %s" % (os.path.relpath(path, MODULE_DIR), match.group(0))
                                  for match in pattern.finditer(source.read())]
        self.assertFalse(found)

    def test_surcharges_apres_expense_scan(self):
        """Avec expense_scan, les surcharges du module passent avant ses méthodes, quel que soit
        l'ordre d'installation : mission_report est chargé après lui."""
        if not _has_expense_scan(self.env):
            self.skipTest("expense_scan is not installed")
        Expense = self.env['hr.expense']
        for name in ('_expense_scan_orders_of', '_expense_scan_projects_of', '_expense_scan_in_period'):
            owner = next(cls for cls in type(Expense).__mro__ if name in vars(cls))
            self.assertEqual(owner.__module__, 'odoo.addons.mission_report.models.mission_orders', name)

    def test_champ_projet_des_depenses(self):
        """Les IGD portent leur mission : le champ existe sans expense_scan."""
        field = self.env['hr.expense']._fields['project_id']
        self.assertEqual(field.comodel_name, 'project.project')
        self.assertTrue(field.store)

    def test_migration_reporte_le_modele_excel(self):
        """Le modèle Excel choisi sur l'affaire passe sur chaque projet de la mission."""
        cr = self.env.cr
        partner = self.env['res.partner'].create({'name': "Client migration"})
        service = self.env['product.product'].create({'name': "Jours migration", 'type': 'service'})
        own, line_project, sold, reinvoiced, kept, alone = self.env['project.project'].create([
            {'name': "Projet de l'affaire"}, {'name': "Projet de la ligne"}, {'name': "Projet vendu"},
            {'name': "Projet refacturé"}, {'name': "Projet qui a son modèle"}, {'name': "Projet seul"}])
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'project_id': own.id,
            'order_line': [Command.create({'product_id': service.id, 'project_id': line_project.id})]})
        other = self.env['sale.order'].create({'partner_id': partner.id, 'project_id': kept.id})
        sold.sale_line_id = order.order_line
        reinvoiced.reinvoiced_sale_order_id = order
        if _has_expense_scan(self.env):
            Template = self.env['expense.scan.export.template']
            template, previous = Template.create([{'name': "Modèle du client"}, {'name': "Modèle déjà choisi"}])
            kept.expense_scan_sheet_template_id = previous
            template, previous = template.id, previous.id
        else:
            # expense_scan à une version antérieure : la colonne du projet est créée.
            template, previous = 41, None
        self.env.flush_all()
        cr.execute("ALTER TABLE sale_order ADD COLUMN mission_expense_template_id integer")
        cr.execute("UPDATE sale_order SET mission_expense_template_id = %s WHERE id IN %s",
                   (template, (order.id, other.id)))

        migration = _migration('19.0.2.2.1', 'post-migrate.py')
        for _again in range(2):
            migration.migrate(cr, '19.0.2.1.0')
            cr.execute("SELECT id, expense_scan_sheet_template_id FROM project_project WHERE id IN %s",
                       (tuple((own | line_project | sold | reinvoiced | kept | alone).ids),))
            values = dict(cr.fetchall())
            self.assertEqual(values, {
                own.id: template, line_project.id: template, sold.id: template, reinvoiced.id: template,
                kept.id: previous or template, alone.id: None})
        self.env.invalidate_all()

    def test_migration_sans_colonne(self):
        """Une base déjà à jour (ou neuve) : rien à reprendre."""
        self.env.flush_all()
        self.env.cr.execute("SELECT count(*) FROM information_schema.columns "
                            "WHERE table_name = 'sale_order' AND column_name = 'mission_expense_template_id'")
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        _migration('19.0.2.2.1', 'post-migrate.py').migrate(self.env.cr, '19.0.2.1.0')


class TestIndependanceCourriel(TestSaleDelivery):
    """Le courriel d'une facture de mission, avec ou sans les fichiers d'expense_scan."""

    def _invoice(self):
        self._validate(self.report)
        invoice = self.order._create_invoices()
        invoice.invoice_date = '2031-06-02'
        return invoice

    def test_courriel_sans_expense_scan(self):
        """Sans expense_scan : la commande et le CRA, ni tableau des frais ni erreur."""
        invoice = self._invoice()
        Move = self.env.registry['account.move']
        absent = lambda record, name: name != 'expense_scan_sheet_files' and hasattr(record, name)  # noqa: E731
        with patch.object(account_move_module, 'hasattr', absent, create=True), \
                patch.object(Move, 'expense_scan_sheet_files', create=True,
                             side_effect=AssertionError("expense_scan is absent")):
            files = invoice._mission_mail_files()
        names = [name for name, _content, _mimetype in files]
        self.assertTrue(any(name.startswith('Commande_') for name in names), names)
        self.assertIn('CRA_Sale Employee_05-2031.pdf', names)
        self.assertNotIn(XLSX, [mimetype for _name, _content, mimetype in files])

    def test_courriel_avec_expense_scan(self):
        """Avec expense_scan : ses fichiers suivent ceux de la mission, pour les projets de la facture."""
        if not _has_expense_scan(self.env):
            self.skipTest("expense_scan is not installed")
        invoice = self._invoice()
        sheet = [("Frais.xlsx", b"xlsx", XLSX), ("Justificatifs.pdf", b"%PDF", 'application/pdf')]
        Move = self.env.registry['account.move']
        with patch.object(Move, 'expense_scan_sheet_files', return_value=sheet) as sheet_files:
            files = invoice._mission_mail_files()
        self.assertEqual(files[-2:], sheet)
        _expenses, projects = sheet_files.call_args.args
        self.assertEqual(projects, self.project_a)
