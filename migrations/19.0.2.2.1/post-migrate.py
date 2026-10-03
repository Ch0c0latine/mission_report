# -*- coding: utf-8 -*-
"""Le modèle Excel des frais passe de l'affaire au projet.

Jusqu'à la version 19.0.2.1.0, il se choisissait sur l'affaire (colonne
``mission_expense_template_id`` de ``sale_order``) ; il est désormais porté par le projet
(``expense_scan_sheet_template_id``, champ du module expense_scan). Odoo supprime la colonne
de l'affaire à la fin de cette mise à jour : la valeur est reportée avant, sur chaque projet
de la mission qui n'a pas encore de modèle, que expense_scan soit déjà à jour ou non.
"""


def _has_column(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
               (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _has_column(cr, 'sale_order', 'mission_expense_template_id'):
        return
    if not _has_column(cr, 'project_project', 'expense_scan_sheet_template_id'):
        # expense_scan pas encore à jour : sa colonne est créée ici, il la reprendra (avec sa
        # clé étrangère) à sa propre mise à jour.
        cr.execute("ALTER TABLE project_project ADD COLUMN expense_scan_sheet_template_id integer")
    # Les projets d'une affaire : le sien, ceux de ses lignes, ceux qui la refacturent.
    links = ["SELECT id AS order_id, project_id FROM sale_order WHERE project_id IS NOT NULL",
             "SELECT order_id, project_id FROM sale_order_line WHERE project_id IS NOT NULL"]
    if _has_column(cr, 'project_project', 'sale_line_id'):
        links.append("SELECT l.order_id, p.id FROM project_project p "
                     "JOIN sale_order_line l ON l.id = p.sale_line_id")
    if _has_column(cr, 'project_project', 'reinvoiced_sale_order_id'):
        links.append("SELECT reinvoiced_sale_order_id, id FROM project_project "
                     "WHERE reinvoiced_sale_order_id IS NOT NULL")
    # Un projet de plusieurs affaires prend le modèle de la plus récente.
    cr.execute("""
        UPDATE project_project p
           SET expense_scan_sheet_template_id = chosen.template_id
          FROM (SELECT DISTINCT ON (link.project_id)
                       link.project_id, o.mission_expense_template_id AS template_id
                  FROM ({links}) AS link
                  JOIN sale_order o ON o.id = link.order_id
                 WHERE o.mission_expense_template_id IS NOT NULL AND o.state != 'cancel'
                 ORDER BY link.project_id, o.id DESC) AS chosen
         WHERE p.id = chosen.project_id
           AND p.expense_scan_sheet_template_id IS NULL
    """.format(links=" UNION ".join(links)))
