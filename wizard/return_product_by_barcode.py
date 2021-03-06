# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from datetime import datetime, timedelta
import hashlib

from openerp import api, fields, models, _
import openerp.addons.decimal_precision as dp
from openerp.exceptions import UserError, ValidationError
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

        return valid_date

    def _compute_wizard_hash(self):
        """Computes default value of field wizard hash"""

        wizard_hash = hashlib.md5(
            str(self.id) +
            datetime.now().strftime('%Y-%m-%d %H:%M:%S %f')
        ).hexdigest()

        return wizard_hash

    customer_id = fields.Many2one('res.partner', 'Customer', domain=[
                                  ('customer', '=', True)], required=True)
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
    total_category_ids = fields.One2many(
        'return.product.total.category',
        'wizard_id',
        'Total returns by Category')

    @api.model
    def _get_picking(self, customer, product, expired=False):
        """Returns stock picking"""

        customer.ensure_one()
        product.ensure_one()

        StockPicking = self.env['stock.picking']

        if expired:
            domain_search = [
                ('company_id', '=', self.env.user.company_id.id),
                ('partner_id', '=', customer.id),
                ('move_lines_related.product_id', '=', product.id),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id', '!=', False),
                ('sale_id.state', 'in', ['sale', 'done']),
                ('state', '=', 'done'),
            ]
            order_search = 'min_date desc'

        else:
            domain_search = [
                ('company_id', '=', self.env.user.company_id.id),
                ('partner_id', '=', customer.id),
                ('sale_id.date_order', '>=', self._get_valid_date()),
                ('move_lines_related.product_id', '=', product.id),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id', '!=', False),
                ('sale_id.state', 'in', ['sale', 'done']),
                ('state', '=', 'done'),
            ]
            order_search = 'min_date'

        pickings = StockPicking.search(domain_search, order=order_search)

        if pickings:

            for picking in pickings:

                pickings_childs_returned = StockPicking.search([
                    ('origin', '=', picking.name),
                    ('move_lines_related.product_id', '=', product.id),
                    ('state', '=', 'done'),
                    ('picking_type_code', '=', 'incoming'),
                ])

                pck_moves_product = picking.move_lines_related.filtered(
                    lambda move: move.product_id.id == product.id
                    and move.state == 'done')

                pck_product_qty_total = sum(
                    pck_moves_product.mapped('product_uom_qty'))

                ReturnReasonProductQty = self.env['return.reason.product.qty']
                # TODO: no more than one instance of the wizard is being considered simultaneously.
                # Fix this.
                picking_taken = ReturnReasonProductQty.search([
                    ('wizard_hash', '=', self.wizard_hash),
                    ('product_id', '=', product.id),
                    ('picking_id', '=', picking.id),
                    ('completed', '=', False),
                ])

                if not pickings_childs_returned:

                    if len(picking_taken) < pck_product_qty_total:
                        return picking

                else:

                    pck_returned_moves_with_product = \
                        pickings_childs_returned.mapped('move_lines_related').filtered(
                            lambda move: move.product_id.id == product.id and
                            move.state == 'done'
                        )

                    pickings_returned_product_qty_total = sum(
                        pck_returned_moves_with_product.mapped(
                            'product_uom_qty')
                    )

                    if (pickings_returned_product_qty_total +
                        len(picking_taken)) < \
                       pck_product_qty_total:

                        return picking
        return False

    @api.model
    def _get_sale_product_price(self, sale_order, product):
        """Returns unit price of product in sale order"""

        line_product = sale_order.order_line.filtered(
            lambda line: line.product_id.id == product.id)

        product_price = line_product[0].price_unit

        for tax in line_product[0].tax_id:

            product_price += tax.amount * line_product[0].price_unit / 100

        return product_price

    @api.model
    def _get_move_product(self, picking, product):
        """Returns the move of product in the picking"""

        picking_product_moves = picking.move_lines.filtered(
            lambda move: not move.scrapped and
            move.product_id.id == product.id)

        return picking_product_moves[0]

    @api.onchange('product_barcode')
    def onchange_product_barcode(self):

        if self.product_barcode:

            if not self.customer_id:
                raise UserError(
                    _('You must indicate the customer')
                )

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
                            'reason_return_id': return_reason_unit.reason_return_id.id,
                            'wizard_hash': return_reason_unit.wizard_hash,
                            'record_hash': return_reason_unit.record_hash,
                            'picking_id': return_reason_unit.picking_id and
                            return_reason_unit.picking_id.id,
                            'sale_product_price':
                            return_reason_unit.sale_product_price,
                            'picking_move_id':
                            return_reason_unit.picking_move_id,
                        })
                    )

                return_reason_unit_hash = hashlib.md5(
                    self.wizard_hash +
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S %f') +
                    str(self.product_id.id)
                ).hexdigest()

                picking = self._get_picking(self.customer_id, product)
                reason_return_id = False

                if not picking:

                    picking = self._get_picking(
                        self.customer_id, product, expired=True)

                    if not picking:
                        raise UserError(
                            _('No sales confirmed of this product were found for this customer'))

                    StockWarehouseReturn = self.env['stock.warehouse.return']
                    expired_reason_return = StockWarehouseReturn.search([
                        ('expired', '=', True),
                    ])

                    if expired_reason_return:
                        reason_return_id = expired_reason_return[0].id

                sale_product_price = self._get_sale_product_price(
                    picking.sale_id, product)
                picking_move = self._get_move_product(
                    picking, product)
                picking_move_id = picking_move and picking_move.id

                return_reason_unit_data = {
                    'product_id': self.product_id.id,
                    'product_uom_qty': 1,
                    'wizard_hash': self.wizard_hash,
                    'record_hash': return_reason_unit_hash,
                    'picking_id': picking and picking.id,
                    'sale_product_price': sale_product_price,
                    'reason_return_id': reason_return_id,
                    'picking_move_id': picking_move_id,
                }

                ReturnReasonProductQty.create(return_reason_unit_data)

                return_reason_qty_ids.append(
                    (0, 0, return_reason_unit_data))
                self.return_reason_qty_ids = return_reason_qty_ids

            else:
                raise ValidationError(
                    _('There is no product with that barcode.'))

    @api.model
    def _do_transfer_return(self, picking):
        self.ensure_one()

        for pack in picking.pack_operation_ids:
            if pack.product_qty > 0:
                pack.write({'qty_done': pack.product_qty})
            else:
                pack.unlink()

        picking.do_transfer()

    @api.model
    def _create_return(self, line_return, return_supplier=False):
        """Returns picking of return of product."""

        if line_return.reason_return_cat_type != 'return_supplier' or \
           not return_supplier:
            picking = line_return.picking_id
            pick_type_id = line_return.reason_return_id.return_picking_type_id.id
            location_dest_id = line_return.return_location_id.id
            move = line_return.picking_move_id

        elif return_supplier:
            StockPicking = self.env['stock.picking']
            picking = StockPicking.search([
                ('name', '=', line_return.picking_purchase_name),
            ])
            if not picking:
                raise UserError(
                    _('The picking receipt %s indicated in product %s does not exist.' %
                      (line_return.picking_purchase_name,
                       line_return.product_id.name)))
            pick_type_id = line_return.reason_return_id.supplier_return_picking_type_id.id
            location_dest_id = line_return.reason_return_id.supplier_return_location_id.id

            picking_move = self._get_move_product(
                picking, line_return.product_id)
            move = picking_move and picking_move.id

        if picking.state != 'done':
            raise UserError(
                _("You may only return pickings that are Done!"))

        StockMove = self.env['stock.move']

        # Cancel assignment of existing chained assigned moves
        moves_to_unreserve = []
        for move_line in picking.move_lines:
            to_check_moves = [
                move_line.move_dest_id] if move_line.move_dest_id else []
            while to_check_moves:
                current_move = to_check_moves.pop()
                if current_move.state not in ('done', 'cancel') and \
                   current_move.reserved_quant_ids:

                    moves_to_unreserve.append(current_move.id)

                split_move_ids = StockMove.search([
                    ('split_from', '=', current_move.id),
                ])
                if split_move_ids:
                    to_check_moves += split_move_ids

        if moves_to_unreserve:
            StockMove.browse(moves_to_unreserve).do_unreserve()
            # break the link between moves in order to be able to fix them
            # later if needed
            StockMove.browse(moves_to_unreserve).write({
                'move_orig_ids': False})

        # Create new picking for returned product
        new_picking = picking.copy({
            'move_lines': [],
            'picking_type_id': pick_type_id,
            'state': 'draft',
            'origin': picking.name,
            'location_id': picking.location_dest_id.id,
            'location_dest_id': location_dest_id,
        })

        # The return of a return should be linked with the original's
        # destination move if it was not cancelled
        if move.origin_returned_move_id.move_dest_id.id and \
           move.origin_returned_move_id.move_dest_id.state != 'cancel':

            move_dest_id = move.origin_returned_move_id.move_dest_id.id
        else:
            move_dest_id = False

        move.copy({
            'product_id': line_return.product_id.id,
            'product_uom_qty': line_return.product_uom_qty,
            'picking_id': new_picking.id,
            'state': 'draft',
            'location_id': move.location_dest_id.id,
            'location_dest_id': location_dest_id,
            'picking_type_id': pick_type_id,
            'warehouse_id': picking.picking_type_id.warehouse_id.id,
            'origin_returned_move_id': move.id,
            'procure_method': 'make_to_stock',
            'move_dest_id': move_dest_id,
        })

        new_picking.action_confirm()
        new_picking.action_assign()
        self._do_transfer_return(new_picking)

        return new_picking

    @api.model
    def _get_invoice_line_account(self, product_category, return_supplier=False):
        """Returns account for invoice line"""

        if return_supplier:
            if product_category.property_account_expense_categ_id:
                return product_category.property_account_expense_categ_id
            else:
                if product_category.parent_id:
                    return self._get_invoice_line_account(
                        product_category.parent_id,
                        return_supplier=return_supplier)

        else:
            if product_category.property_account_income_categ_id:
                return product_category.property_account_income_categ_id
            else:
                if product_category.parent_id:
                    return self._get_invoice_line_account(
                        product_category.parent_id,
                        return_supplier=return_supplier)

        return False

    @api.model
    def _create_refund_invoice(self, line_return, return_supplier=False):
        """Create refund invoices for customers or suppliers depending
        on return type"""

        AccountInvoice = self.env['account.invoice']
        AccountInvoiceLine = self.env['account.invoice.line']

        if line_return.reason_return_cat_type != 'return_supplier' or \
           not return_supplier:

            picking = line_return.picking_id

        elif return_supplier:
            StockPicking = self.env['stock.picking']
            picking = StockPicking.search([
                ('name', '=', line_return.picking_purchase_name),
            ])
            if not picking:
                raise UserError(
                    _('The picking receipt %s indicated in product %s does not exist.' % (
                        line_return.picking_purchase_name,
                        line_return.product_id.name)))

        if picking.picking_type_code == 'incoming' and \
           picking.purchase_id:

            invoices = picking.purchase_id.invoice_ids.filtered(
                lambda inv: inv.state != 'cancel'
            )

            if line_return.product_id.supplier_taxes_id:
                invoice_line_taxes_id = [
                    (4, tax.id)
                    for tax in
                    line_return.product_id.supplier_taxes_id
                ]
            else:
                invoice_line_taxes_id = False

            invoice_line_account_id = False
            if line_return.product_id.property_account_expense_id:

                invoice_line_account_id = line_return.product_id.property_account_expense_id.id

            elif line_return.product_id.categ_id:
                invoice_line_account = self._get_invoice_line_account(
                    line_return.product_id.categ_id,
                    return_supplier=return_supplier)
                invoice_line_account_id = invoice_line_account and \
                    invoice_line_account.id

            if not invoice_line_account_id:
                raise UserError(
                    _('You must set up an expense account for the product %s' %
                      line_return.product_id.name))

            invoice_line_name = line_return.product_id.description_purchase

        elif picking.picking_type_code == 'outgoing' and \
                picking.sale_id:

            invoices = picking.sale_id.invoice_ids.filtered(
                lambda inv: inv.state != 'cancel'
            )

            if line_return.product_id.taxes_id:
                invoice_line_taxes_id = [
                    (4, tax.id)
                    for tax in
                    line_return.product_id.taxes_id
                ]
            else:
                invoice_line_taxes_id = False

            invoice_line_account_id = False
            if line_return.product_id.property_account_income_id:

                invoice_line_account_id = line_return.product_id.property_account_income_id.id

            elif line_return.product_id.categ_id:
                invoice_line_account = self._get_invoice_line_account(
                    line_return.product_id.categ_id,
                    return_supplier=return_supplier)
                invoice_line_account_id = invoice_line_account and \
                    invoice_line_account.id

            if not invoice_line_account_id:
                raise UserError(
                    _('You must set up an income account for the product %s' %
                      line_return.product_id.name))

            invoice_line_name = line_return.product_id.description_sale

        invoice_origin = False

        if invoices:
            invoice_origin = invoices[0]
            if picking.picking_type_code == 'incoming':
                refund_invoice_type = 'in_refund'
                uom_id = line_return.product_id.uom_po_id and \
                    line_return.product_id.uom_po_id.id
            else:
                refund_invoice_type = 'out_refund'
                uom_id = line_return.product_id.uom_id and \
                    line_return.product_id.uom_id.id

            refund_invoice_data = {
                'type': refund_invoice_type,
                'origin': invoice_origin.number,
                'partner_id': invoices[0].partner_id.id,
                'currency_id': invoices[0].currency_id.id,
                'company_id': invoices[0].company_id.id,
            }

            invoice_origin_product_line = invoice_origin.invoice_line_ids.filtered(
                lambda line: line.product_id.id == line_return.product_id.id
            )

            product_price_unit = invoice_origin_product_line[0].price_unit

        elif picking.picking_type_code == 'incoming' and \
                picking.purchase_id:

            refund_invoice_data = {
                'type': 'in_refund',
                'partner_id': picking.partner_id.id,
                'currency_id': picking.purchase_id.currency_id.id,
                'company_id': picking.purchase_id.company_id.id,
            }

            purchase_product_line = picking.purchase_id.order_line.filtered(
                lambda line: line.product_id.id == line_return.product_id.id
            )

            product_price_unit = purchase_product_line[0].price_unit

            uom_id = line_return.product_id.uom_po_id and \
                line_return.product_id.uom_po_id.id

        elif picking.picking_type_code == 'outgoing' and \
                picking.sale_id:

            refund_invoice_data = {
                'type': 'out_refund',
                'partner_id': picking.partner_id.id,
                'currency_id': picking.sale_id.currency_id.id,
                'company_id': picking.sale_id.company_id.id,
            }

            sale_product_line = picking.sale_id.order_line.filtered(
                lambda line: line.product_id.id == line_return.product_id.id
            )

            product_price_unit = sale_product_line[0].price_unit

            uom_id = line_return.product_id.uom_id and \
                line_return.product_id.uom_id.id

        refund_invoice = AccountInvoice.create(refund_invoice_data)

        # The next lines of try applies only for MX
        try:
            refund_invoice.write({
                'validate_attachment': True,
                'validate_attachment2': True,
            })
        except Exception:
            _logger.debug('MX l10n modules are not installed')
            pass

        if not invoice_line_name:
            invoice_line_name = line_return.product_id.name

        AccountInvoiceLine.create({
            'name': invoice_line_name,
            'invoice_id': refund_invoice.id,
            'product_id': line_return.product_id.id,
            'quantity': line_return.product_uom_qty,
            'price_unit': product_price_unit,
            'partner_id': refund_invoice.partner_id.id,
            'account_id': invoice_line_account_id,
            'invoice_line_tax_ids': invoice_line_taxes_id,
            'uom_id': uom_id,
        })

        refund_invoice.compute_taxes()

    @api.multi
    def return_product(self):
        """Proccess returns of product"""

        self.ensure_one()

        total_returns_category = dict()

        for line_return in self.return_reason_qty_ids:

            self._create_return(line_return)

            if line_return.reason_return_cat_type == 'return_supplier':
                self._create_return(line_return, return_supplier=True)

            ReturnReasonProductQty = self.env['return.reason.product.qty']
            line_return_stored = ReturnReasonProductQty.search([
                ('wizard_hash', '=', line_return.wizard_hash),
                ('record_hash', '=', line_return.record_hash),
                ('product_id', '=', line_return.product_id.id),
                ('picking_id', '=', line_return.picking_id.id),
                ('completed', '=', False),
            ])

            if line_return_stored:
                line_return_stored.write({'completed': True})

            if line_return.reason_return_cat_type != 'no_accepted':
                self._create_refund_invoice(line_return)
                if line_return.reason_return_cat_type == 'return_supplier':
                    self._create_refund_invoice(
                        line_return, return_supplier=True)

            if str(line_return.reason_return_id.category_id.id) \
               not in total_returns_category:

                total_returns_category.update({
                    str(line_return.reason_return_id.category_id.id):
                    line_return.product_uom_qty
                })

            else:
                total_returns_category[
                    str(line_return.reason_return_id.category_id.id)] += \
                    line_return.product_uom_qty

        if total_returns_category:
            total_category_ids = list()

            for categ_id in total_returns_category:
                total_category_ids.append((0, 0, {
                    'reason_return_categ_id': int(categ_id),
                    'total': total_returns_category[categ_id],
                }))

            self.total_category_ids = total_category_ids
            return {
                'name': _('Total Returns by Category'),
                'context': self._context,
                'view_type': 'form',
                'view_mode': 'tree',
                'res_model': 'return.product.total.category',
                'type': 'ir.actions.act_window',
                'domain': [('wizard_id', '=', self.id)],
            }


class ReturnProductReasonUnit(models.TransientModel):
    _name = 'return.product.reason.unit'

    wizard_id = fields.Many2one(
        'return.product.barcode', 'Wizard', required=True)
    reason_return_id = fields.Many2one(
        'stock.warehouse.return', 'Return Reason')
    reason_return_cat_type = fields.Selection(
        related='reason_return_id.category_type')
    reason_return_expired = fields.Boolean(related='reason_return_id.expired')
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
    picking_id = fields.Many2one('stock.picking', 'Transfer')
    sale_id = fields.Many2one(related='picking_id.sale_id')
    sale_date_order = fields.Datetime(related='sale_id.date_order')
    sale_product_price = fields.Float(
        'Amount', digits=dp.get_precision('Product Price'), default=0.0)
    picking_purchase_name = fields.Char('Picking Name of Purchase')
    picking_move_id = fields.Many2one('stock.move', 'Move of product')

    @api.onchange('reason_return_id', 'picking_purchase_name')
    def onchange_fields(self):

        ReturnReasonProductQty = self.env['return.reason.product.qty']

        return_reason_product_rec = ReturnReasonProductQty.search([
            ('wizard_hash', '=', self.wizard_hash),
            ('record_hash', '=', self.record_hash),
        ])

        if return_reason_product_rec:

            if self.reason_return_id:
                return_reason_product_rec.write({
                    'reason_return_id': self.reason_return_id.id})

            if self.picking_purchase_name:
                return_reason_product_rec.write({
                    'picking_purchase_name': self.picking_purchase_name})


class ReturnProductTotalCategory(models.TransientModel):
    _name = 'return.product.total.category'

    total = fields.Float('Total', required=True)
    reason_return_categ_id = fields.Many2one(
        'stock.warehouse.return.category', 'Category', required=True)
    wizard_id = fields.Many2one(
        'return.product.barcode', 'Wizard', required=True)
