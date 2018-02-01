# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from openerp import fields, models


class ReturnReasonProductQty(models.Model):
    _name = 'return.reason.product.qty'

    reason_return_id = fields.Many2one(
        'stock.warehouse.return', 'Return Reason')
    return_location_id = fields.Many2one(
        related='reason_return_id.return_location_id', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_uom_qty = fields.Float(
        'Quantity', required=True, default=1, readonly=True)
    product_attribute_value_ids = fields.Many2many(
        related='product_id.attribute_value_ids', readonly=True)
    product_default_code = fields.Char(
        related='product_id.default_code', readonly=True)
    wizard_hash = fields.Char('Wizard hash')
    record_hash = fields.Char('Record hash')
