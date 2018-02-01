# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from datetime import datetime, timedelta
import hashlib

from openerp import api, fields, models, _
from openerp.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class ReturnProductBarcode(models.TransientModel):
    _name = 'return.product.barcode'

    def _get_valid_date(self):
        """Returns min date valid for returns"""

        expiration_days_qty = \
            self.env.user.company_id.sale_return_time_expiration_days

        valid_datetime = datetime.now() - timedelta(days=expiration_days_qty)
        valid_date = valid_datetime.strftime('%Y-%m-%d')
        _logger.debug('DEBUG VALID DATE RETURNS %s', valid_date)
        return valid_date

    def _compute_wizard_hash(self):
        """Computes default value of field wizard hash"""

        wizard_hash = hashlib.md5(
            str(self.id) +
            datetime.now().strftime('%Y-%m-%d %H:%M:%S %f')
        ).hexdigest()

        return wizard_hash

    customer_id = fields.Many2one('res.partner', 'Customer', domain=[
                                  ('customer', '=', True)])
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_barcode = fields.Char(
        'Barcode',
        help="International Article Number used for product identification.")
    product_image_medium = fields.Binary(
        related='product_id.image_medium', readonly=True)
    product_name = fields.Char(related='product_id.name', readonly=True)
    product_attribute_value_ids = fields.Many2many(
        related='product_id.attribute_value_ids', readonly=True)
    product_default_code = fields.Char(
        related='product_id.default_code', readonly=True)
    product_volume = fields.Float(related='product_id.volume', readonly=True)
    product_weight = fields.Float(related='product_id.weight', readonly=True)
    return_reason_qty_ids = fields.One2many(
        'return.product.reason.unit',
        'wizard_id',
        'Quantity by reason',
        required=True)
    wizard_hash = fields.Char('Wizard hash', default=_compute_wizard_hash)

    @api.onchange('product_barcode')
    def onchange_product_barcode(self):

        if self.product_barcode:

            ProductProduct = self.env['product.product']
            product = ProductProduct.search(
                [('barcode', '=', self.product_barcode)])

            if product:
                self.product_id = product[0]
                self.product_barcode = False

                return_reason_qty_ids = list()
                ReturnReasonProductQty = self.env['return.reason.product.qty']
                return_reason_product_lines = ReturnReasonProductQty.search([
                    ('wizard_hash', '=', self.wizard_hash),
                ])

                for return_reason_unit in return_reason_product_lines:

                    return_reason_qty_ids.append(
                        (0, 0, {
                            'product_id': return_reason_unit.product_id.id,
                            'product_uom_qty': return_reason_unit.product_uom_qty,
                            'reason_return_id': return_reason_unit.reason_return_id,
                            'wizard_hash': return_reason_unit.wizard_hash,
                            'record_hash': return_reason_unit.record_hash,
                        })
                    )

                return_reason_unit_hash = hashlib.md5(
                    self.wizard_hash +
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S %f') +
                    str(self.product_id.id)
                ).hexdigest()

                return_reason_unit_data = {
                    'product_id': self.product_id.id,
                    'product_uom_qty': 1,
                    'wizard_hash': self.wizard_hash,
                    'record_hash': return_reason_unit_hash,
                }

                ReturnReasonProductQty.create(return_reason_unit_data)

                return_reason_qty_ids.append(
                    (0, 0, return_reason_unit_data))
                self.return_reason_qty_ids = return_reason_qty_ids

            else:
                raise ValidationError(
                    _('There is no product with that barcode.'))

    @api.multi
    def return_product_by_barcode(self):
        """Proccess returns of product"""

        self.ensure_one()

        wizard = self
        product = wizard.product_id

        if wizard.return_reason_qty_ids:

            StockPicking = self.env['stock.picking']

            pickings = StockPicking.search([
                ('company_id', '=', self.env.user.company_id.id),
                ('partner_id', '=', wizard.customer_id.id),
                ('sale_id.date_order', '>=', self._get_valid_date),
                ('move_lines_related.product_id', '=', product.id),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id.state', 'in', ['sale', 'done']),
            ], order='min_date')

            _logger.debug('DEBUG PICKINGS %s', pickings)
            if pickings:

                pickings_to_return = list()
                product_qty_return_by_picking = dict()

                for picking in pickings:

                    pickings_childs = StockPicking.search([
                        ('origin', '=', picking.name),
                        ('move_lines_related.product_id', '=', product.id),
                        ('state', '=', 'done'),
                    ])

                    pickings_returned = pickings_childs.filtered(
                        lambda pck: pck.location_dest_return_location or
                        pck.location_dest_id.usage == 'internal'
                    )

                    pck_moves_product = picking.move_lines_related.filtered(
                        lambda move: move.product_id.id == product.id
                        and move.state == 'done')

                    pck_product_qty_total = sum(
                        pck_moves_product.mapped('product_uom_qty'))

                    if not pickings_returned:

                        pickings_to_return.append(picking)
                        product_qty_return_by_picking[
                            str(picking.id)] = pck_product_qty_total

                    else:

                        pck_returned_moves_with_product = pickings_returned.move_lines_related.filtered(
                            lambda move: move.product_id.id == product.id and
                            move.state == 'done'
                        )

                        pickings_returned_product_qty_total = sum(
                            pck_returned_moves_with_product.mapped(
                                'product_uom_qty')
                        )

                        if pickings_returned_product_qty_total < pck_product_qty_total:

                            pickings_to_return.append(picking)
                            product_qty = pck_product_qty_total - \
                                pickings_returned_product_qty_total
                            product_qty_return_by_picking[
                                str(picking.id)] = product_qty

                _logger.debug('DEBUG PICKINGS TO RETURN %s',
                              pickings_to_return)
                _logger.debug('DEBUG product_qty_return_by_picking %s',
                              product_qty_return_by_picking)


class ReturnProductReasonUnit(models.TransientModel):
    _name = 'return.product.reason.unit'

    wizard_id = fields.Many2one(
        'return.product.barcode', 'Wizard', required=True)
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
    wizard_hash = fields.Char('Wizard hash', required=True)
    record_hash = fields.Char('Record hash', required=True)

    @api.onchange('reason_return_id')
    def onchange_reason_return_id(self):

        ReturnReasonProductQty = self.env['return.reason.product.qty']

        return_reason_product_rec = ReturnReasonProductQty.search([
            ('wizard_hash', '=', self.wizard_hash),
            ('record_hash', '=', self.record_hash),
        ])

        if return_reason_product_rec:
            return_reason_product_rec.write({
                'reason_return_id': self.reason_return_id.id})
