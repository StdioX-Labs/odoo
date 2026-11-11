/** @odoo-module **/

import { _t } from '@web/core/l10n/translation';
import { rpc, RPCError } from '@web/core/network/rpc';
import paymentForm from '@payment/js/payment_form';

paymentForm.include({

    /**
     * M-Pesa collects the phone number inline and pays by STK Push: direct flow.
     *
     * @override method from @payment/js/payment_form
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'mpesa') {
            this._super(...arguments);
            return;
        } else if (flow === 'token') {
            return;
        }
        this._setPaymentFlow('direct');
    },

    /**
     * Check the phone number before a transaction is created for it.
     *
     * @override method from @payment/js/payment_form
     */
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode === 'mpesa' && flow !== 'token' && !this._mpesaGetPhone()) {
            this._displayErrorDialog(
                _t("M-Pesa"), _t("Enter the M-Pesa phone number you want to pay with.")
            );
            this._enableButton();
            return;
        }
        await this._super(...arguments);
    },

    /**
     * Send the STK Push, then wait on the status page while the customer enters their PIN.
     *
     * @override method from @payment/js/payment_form
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'mpesa') {
            this._super(...arguments);
            return;
        }
        try {
            await rpc('/payment/mpesa/stk_push', {
                reference: processingValues.reference,
                access_token: processingValues.mpesa_access_token,
                phone_number: this._mpesaGetPhone(),
            });
            window.location = '/payment/status';
        } catch (error) {
            if (!(error instanceof RPCError)) {
                throw error;
            }
            this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
            this._enableButton();
        }
    },

    _mpesaGetPhone() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const input = radio && this._getInlineForm(radio)?.querySelector('input[name="mpesa_phone"]');
        return input ? input.value.trim() : '';
    },

});
