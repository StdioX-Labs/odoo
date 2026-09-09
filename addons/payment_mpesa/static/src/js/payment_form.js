/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.MpesaPaymentForm = publicWidget.Widget.extend({
    selector: '.mpesa_payment_container',
    events: {
        'click #mpesa_pay_button': '_onClickPay',
    },

    _onClickPay: async function (ev) {
        ev.preventDefault();
        const $button = $(ev.currentTarget);
        const phoneNumber = $('#mpesa_phone').val().trim();
        const txId = parseInt($button.data('tx-id'));

        if (!phoneNumber) {
            this._showMessage('error', _t('Please enter your phone number'));
            return;
        }

        $button.prop('disabled', true);
        $('#mpesa_loading').show();
        this._hideMessage();

        try {
            const data = await rpc('/payment/mpesa/initiate', {
                tx_id: txId,
                phone_number: phoneNumber,
            });

            if (data.success) {
                this._showMessage('success', data.message || _t('Payment initiated successfully'));
                setTimeout(function () {
                    window.location.reload();
                }, 3000);
            } else {
                this._showMessage('error', data.error || _t('Payment failed'));
                $button.prop('disabled', false);
                $('#mpesa_loading').hide();
            }
        } catch (error) {
            this._showMessage('error', _t('An error occurred. Please try again.'));
            $button.prop('disabled', false);
            $('#mpesa_loading').hide();
        }
    },

    _showMessage: function (type, message) {
        const $msg = $('#mpesa_message');
        $msg.removeClass('alert-success alert-danger alert-info');
        $msg.addClass(type === 'success' ? 'alert-success' : 'alert-danger');
        $msg.text(message);
        $msg.show();
    },

    _hideMessage: function () {
        $('#mpesa_message').hide();
    },
});

export default publicWidget.registry.MpesaPaymentForm;
