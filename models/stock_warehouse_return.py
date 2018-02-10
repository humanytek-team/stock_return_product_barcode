# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from openerp import fields, models


class StockWarehouseReturn(models.Model):
    _inherit = 'stock.warehouse.return'

    return_location_id = fields.Many2one(
        'stock.location',
        'Return Location',
        ondelete='restrict',
        required=True)
    expired = fields.Boolean('Time Expired')
    category_id = fields.Many2one(
        'stock.warehouse.return.category', 'Category', required=True)
    category_type = fields.Selection(related='category_id.type')
    return_picking_type_id = fields.Many2one(
        'stock.picking.type', 'Picking Type for Returns', required=True)
    supplier_return_location_id = fields.Many2one(
        'stock.location',
        'Supplier Return Location',
        ondelete='restrict')
    supplier_return_picking_type_id = fields.Many2one(
        'stock.picking.type', 'Picking Type for Returns of Suppliers')


class StockWarehouseReturnCategory(models.Model):
    _name = 'stock.warehouse.return.category'

    name = fields.Char('Category')
    active = fields.Boolean('Active ?', default=True)
    type = fields.Selection([
        ('accepted', 'Accepted'),
        ('no_accepted', 'No Accepted'),
        ('return_supplier', 'Return to Supplier'),
    ], 'Type of Category', required=True)
